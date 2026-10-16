"""
control.py - How fast do the fans run? (fan control)

Modes (YAML: fans.control.mode):
  full       fans run at full speed between on_hour and off_hour
  sun        fans are powered directly by a small solar panel: speed follows the sunshine
  fixed_pwm  the Arduino writes a constant PWM value (fans.control.fixed_pwm)
  pid        the Arduino runs a PID temperature controller that writes a PWM value

The PID is an exact copy of the Arduino library PID_v1_bc (David Forrest,
based on Brett Beauregard's PID_v1), so the Kp, Ki, Kd values from the
prototype's Arduino sketch can be used unchanged. Library source:
https://github.com/drf5n/Arduino-PID-Library (branch PID_v1_bc)

PWM -> fan speed (2-pin fan switched by a PWM output, e.g. through a MOSFET):
  The fan's average voltage is proportional to the PWM value, but a fan cannot
  turn arbitrarily slowly. Below 'stop_below' the fan stands still; a standing
  fan needs at least 'start_at' to start again. In between the speed rises
  linearly from 'speed_at_stop_below' to 1.0 at PWM 255. A measured table
  (fans.pwm.curve) can replace this straight line.

Timing (important for comparing with the prototype):
  The simulation moves in steps of run.time_step_s (e.g. 30 s), but the
  Arduino computes the PID much more often. Inside every simulation step the
  controller is therefore run with its own clock (every sample_time_ms or
  slower, see loop_period_ms). The sensor values it reads are those of the
  previous simulation step, interpolated in time (so the controller "sees" the
  dryer with a delay of one time step - keep time_step_s small, e.g. 10-30 s).
  The fans get the average speed over the step.
"""

import math

import numpy as np

AUTOMATIC, MANUAL = 1, 0


class PIDv1bc:
    """Python port of PID_v1_bc (Arduino). Variable names follow the C++ code."""

    def __init__(self, Kp, Ki, Kd, p_on_error, reverse, sample_time_ms, out_min, out_max):
        self.out_min, self.out_max = out_min, out_max
        self.sample_time_ms = sample_time_ms
        self.reverse = reverse
        self.set_tunings(Kp, Ki, Kd, p_on_error)
        self.in_auto = False
        self.output_sum = 0.0
        self.last_input = 0.0
        self.output = 0.0

    def set_tunings(self, Kp, Ki, Kd, p_on_error=True):
        if Kp < 0 or Ki < 0 or Kd < 0:
            raise ValueError("PID: Kp, Ki and Kd must be >= 0 (use 'direction' for the sign)")
        self.p_on_e = p_on_error
        t = self.sample_time_ms / 1000.0
        self.kp, self.ki, self.kd = Kp, Ki * t, Kd / t   # same scaling as SetTunings()
        if self.reverse:
            self.kp, self.ki, self.kd = -self.kp, -self.ki, -self.kd

    def set_mode(self, mode, current_input):
        """SetMode(): switching MANUAL -> AUTOMATIC calls Initialize() (bumpless start)."""
        new_auto = mode == AUTOMATIC
        if new_auto and not self.in_auto:
            self.output_sum = min(max(self.output, self.out_min), self.out_max)
            self.last_input = current_input
        self.in_auto = new_auto

    def compute(self, inp, setpoint):
        """Compute() - called when the sample time has elapsed."""
        if not self.in_auto:
            return self.output
        error = setpoint - inp
        d_input = inp - self.last_input
        self.output_sum += self.ki * error
        if not self.p_on_e:
            self.output_sum -= self.kp * d_input
        self.output_sum = min(max(self.output_sum, self.out_min), self.out_max)
        output = self.kp * error if self.p_on_e else 0.0
        output += self.output_sum - self.kd * d_input
        if output > self.out_max:                         # back-calculation anti-windup
            self.output_sum -= output - self.out_max
            output = self.out_max
        elif output < self.out_min:
            self.output_sum += self.out_min - output
            output = self.out_min
        self.output = output
        self.last_input = inp
        return output


class FanDriver:
    """Turns a PWM value (0..255) into a fan speed fraction (0..1) for a 2-pin fan."""

    def __init__(self, pwm_cfg):
        self.max = pwm_cfg["max_value"]
        self.stop_below = pwm_cfg["stop_below"]
        self.start_at = max(pwm_cfg["start_at"], self.stop_below)
        self.s0 = pwm_cfg["speed_at_stop_below"]
        curve = pwm_cfg.get("curve") or []
        self.curve = np.array(curve, dtype=float) if curve else None
        self.running = False

    def speed(self, pwm):
        # start / stop behaviour (hysteresis)
        if self.running and pwm < self.stop_below:
            self.running = False
        elif not self.running and pwm >= self.start_at:
            self.running = True
        if not self.running:
            return 0.0
        if self.curve is not None:
            return float(np.interp(pwm, self.curve[:, 0], self.curve[:, 1]))
        span = self.max - self.stop_below
        return self.s0 + (1.0 - self.s0) * (pwm - self.stop_below) / span if span > 0 else 1.0


class FanController:
    def __init__(self, cfg):
        f = cfg["fans"]
        self.f = f
        c = f.get("control")
        if c is None:  # old configuration files without a control section
            c = {"mode": "sun" if f.get("speed_follows_sun") else "full"}
        self.c = c
        self.mode = c["mode"]
        if self.mode not in ("full", "sun", "fixed_pwm", "pid"):
            raise ValueError("fans.control.mode must be full, sun, fixed_pwm or pid")
        self.driver = FanDriver(f["pwm"]) if self.mode in ("fixed_pwm", "pid") else None

        if self.mode == "pid":
            p = c["pid"]
            self.setpoint = p["setpoint_C"]
            self.sample_s = p["sample_time_ms"] / 1000.0
            loop_s = max(p["loop_period_ms"], 1) / 1000.0
            # Compute() only runs in a loop() pass where >= SampleTime has elapsed
            self.compute_interval = math.ceil(self.sample_s / loop_s - 1e-9) * loop_s
            self.pid = PIDv1bc(p["Kp"], p["Ki"], p["Kd"],
                               p["proportional_on"] == "error",
                               p["direction"] == "reverse",
                               p["sample_time_ms"], p["output_min"], p["output_max"])
            inp = c["input"]
            self.sources = inp["sources"]
            self.combine = inp["combine"]
            self.resolution = inp["resolution_C"]
            self.read_interval = inp["read_interval_s"]
            self.t_next = 0.0          # Arduino clock [s]: next Compute()
            self.t_last_read = -1e9
            self.reading = None
        self.history = (None, None)    # controller input at the end of the last two steps

    # ------------------------------------------------------------------
    def scheduled(self, hour):
        h = hour % 24.0
        return self.f["on_hour"] <= h < self.f["off_hour"]

    def measured_input(self, out_row, sensors_enabled):
        """The controller input from one row of results (e.g. max of the sensors)."""
        if self.mode != "pid":
            return None
        names = {"air_outlet": "T_air_outlet_C", "air_collector": "T_air_collector_C",
                 "product": "T_product_C", "plate": "T_plate_C"}
        vals = []
        for s in self.sources:
            if s in names:
                vals.append(out_row[names[s]])
            else:
                if not sensors_enabled:
                    raise ValueError(f"control input '{s}' is a sensor, but sensors.enabled is false")
                key = f"sensor_{s}_T_C"
                if key not in out_row:
                    raise KeyError(f"control input '{s}': no sensor with that name in section 14")
                vals.append(out_row[key])
        return {"max": max, "min": min, "mean": lambda v: sum(v) / len(v)}[self.combine](vals)

    def remember(self, value):
        self.history = (self.history[1], value)

    # ------------------------------------------------------------------
    def advance(self, t_end_h, dt, ghi):
        """
        Run the controller from t_end - dt to t_end.
        Returns dict with the average fan speed over the step and diagnostics.
        """
        if self.mode == "full":
            s = 1.0 if self.scheduled(t_end_h) else 0.0
            return {"speed": s, "pwm": 255 * s}
        if self.mode == "sun":
            if not self.scheduled(t_end_h):
                return {"speed": 0.0, "pwm": float("nan")}
            s = min(1.0, ghi / self.f["sun_for_full_speed_W_m2"])
            return {"speed": s if s >= self.f["min_speed_fraction"] else 0.0, "pwm": float("nan")}
        if self.mode == "fixed_pwm":
            pwm = int(self.c["fixed_pwm"]) if self.scheduled(t_end_h) else 0
            return {"speed": self.driver.speed(pwm), "pwm": pwm}

        # ---- PID: run the Arduino clock inside this simulation step ----
        t1 = t_end_h * 3600.0
        t0 = t1 - dt
        a, b = self.history
        if b is None:
            return {"speed": 0.0, "pwm": 0, "input": float("nan"), "pid_output": 0.0,
                    "pid_integral": 0.0}
        if a is None:
            a = b
        speed_sum = 0.0
        t = t0
        pwm = int(self.pid.output)
        speed_now = self.driver.speed(pwm)
        while self.t_next < t1:
            tc = max(self.t_next, t0)
            speed_sum += speed_now * (tc - t)  # speed held since last compute
            t = tc
            # DHT21 reading: only every read_interval, rounded to the sensor resolution
            if tc - self.t_last_read >= self.read_interval or self.reading is None:
                frac = (tc - t0) / dt
                raw = a + (b - a) * frac
                self.reading = round(raw / self.resolution) * self.resolution
                self.t_last_read = tc
            if self.scheduled(tc / 3600.0):
                self.pid.set_mode(AUTOMATIC, self.reading)
                self.pid.compute(self.reading, self.setpoint)
            else:
                self.pid.set_mode(MANUAL, self.reading)
                self.pid.output = 0.0
            pwm = int(self.pid.output)           # analogWrite(pin, Output) truncates
            speed_now = self.driver.speed(pwm)
            self.t_next = tc + self.compute_interval
        speed_sum += speed_now * (t1 - t)
        return {"speed": speed_sum / dt, "pwm": pwm, "input": self.reading,
                "pid_output": self.pid.output, "pid_integral": self.pid.output_sum}
