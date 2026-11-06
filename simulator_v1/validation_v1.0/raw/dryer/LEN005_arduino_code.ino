#include <DHT.h>
#include <PID_v1_bc.h>
#include <SPI.h>
#include <SD.h>

// =====================================================
// LENGKUAS DRYING EXPERIMENT
//
// - DHT1-DHT4: Temperatur + Luftfeuchtigkeit
// - Speicherung JEDE MINUTE
// - Ausgabe JEDE MINUTE im Serial Monitor
// - Fan Speed wird gespeichert
// - Zieltemperatur wird gespeichert
// - 40 / 50 / 60 C jederzeit über Taster
// - Status LED zeigt: Arduino läuft
// - Error LED zeigt Fehler
// =====================================================


// =====================================================
// DHT-SENSOREN
// =====================================================

#define DHTTYPE DHT21

#define DHT_PIN_1 6
#define DHT_PIN_2 7
#define DHT_PIN_3 8
#define DHT_PIN_4 9

DHT dht1(DHT_PIN_1, DHTTYPE);
DHT dht2(DHT_PIN_2, DHTTYPE);
DHT dht3(DHT_PIN_3, DHTTYPE);
DHT dht4(DHT_PIN_4, DHTTYPE);


// Aktuellste Messwerte
float temps[4] = {NAN, NAN, NAN, NAN};
float hums[4]  = {NAN, NAN, NAN, NAN};


// =====================================================
// TASTER
// =====================================================

#define TEMP_BUTTON_40 3
#define TEMP_BUTTON_50 4
#define TEMP_BUTTON_60 5


// =====================================================
// LEDs
// =====================================================

#define STATUS_LED 24
#define ERROR_LED 25


// =====================================================
// SD-KARTE
// =====================================================

#define SD_CS_PIN 53

bool sdOK = false;

char dataFilename[13];


// =====================================================
// LÜFTER
// =====================================================

#define FAN_PIN 10

const int MIN_FAN_SPEED = 80;

int currentFanSpeed = MIN_FAN_SPEED;


// =====================================================
// ZIELTEMPERATUR
// =====================================================

float targetTemp = 50.0;


// =====================================================
// PID
// =====================================================

double inputTemp = 0;
double fanOutput = 0;
double targetTempPID = 50;

double Kp = 500;
double Ki = 0.1;
double Kd = 10;

PID myPID(
  &inputTemp,
  &fanOutput,
  &targetTempPID,
  Kp,
  Ki,
  Kd,
  REVERSE
);


// =====================================================
// ZEITINTERVALLE
// =====================================================

// DHT21 nicht ständig auslesen.
// Alle 3 Sekunden reicht völlig.
const unsigned long SENSOR_INTERVAL = 3000UL;

// Daten jede Minute speichern
const unsigned long LOG_INTERVAL = 60000UL;

// Diagnoseausgabe alle 10 Sekunden
const unsigned long HEARTBEAT_INTERVAL = 10000UL;


// Zeitvariablen
unsigned long experimentStart = 0;

unsigned long lastSensorRead = 0;

unsigned long lastLogTime = 0;

unsigned long lastHeartbeat = 0;


// =====================================================
// DATEINAMEN ERZEUGEN
//
// LEN001.CSV
// LEN002.CSV
// ...
// =====================================================

void createNewFilename() {

  for (int i = 1; i <= 999; i++) {

    snprintf(
      dataFilename,
      sizeof(dataFilename),
      "LEN%03d.CSV",
      i
    );

    if (!SD.exists(dataFilename)) {

      return;
    }
  }

  strcpy(dataFilename, "LEN999.CSV");
}


// =====================================================
// DHT-SENSOREN AUSLESEN
// =====================================================

void readDHTSensors() {

  temps[0] = dht1.readTemperature();
  hums[0]  = dht1.readHumidity();

  temps[1] = dht2.readTemperature();
  hums[1]  = dht2.readHumidity();

  temps[2] = dht3.readTemperature();
  hums[2]  = dht3.readHumidity();

  temps[3] = dht4.readTemperature();
  hums[3]  = dht4.readHumidity();
}


// =====================================================
// TEMPERATURTASTER
// =====================================================

void readButtons() {

  if (digitalRead(TEMP_BUTTON_40) == LOW) {

    if (targetTemp != 40.0) {

      targetTemp = 40.0;

      Serial.println();
      Serial.println("Target temperature changed to 40 C");
    }
  }

  else if (digitalRead(TEMP_BUTTON_50) == LOW) {

    if (targetTemp != 50.0) {

      targetTemp = 50.0;

      Serial.println();
      Serial.println("Target temperature changed to 50 C");
    }
  }

  else if (digitalRead(TEMP_BUTTON_60) == LOW) {

    if (targetTemp != 60.0) {

      targetTemp = 60.0;

      Serial.println();
      Serial.println("Target temperature changed to 60 C");
    }
  }
}


// =====================================================
// LÜFTER REGELN
// =====================================================

void controlFan() {

  float highestTemp = -1000;

  bool validTemperature = false;


  // DHT2-DHT4 sind die Sensoren im Trockner

  for (int i = 1; i < 4; i++) {

    if (!isnan(temps[i])) {

      if (!validTemperature || temps[i] > highestTemp) {

        highestTemp = temps[i];
      }

      validTemperature = true;
    }
  }


  // ===================================================
  // FALLS KEIN INTERNER SENSOR FUNKTIONIERT
  // ===================================================

  if (!validTemperature) {

    // Lüfter trotzdem laufen lassen
    currentFanSpeed = MIN_FAN_SPEED;

    analogWrite(
      FAN_PIN,
      currentFanSpeed
    );

    digitalWrite(
      ERROR_LED,
      HIGH
    );

    return;
  }


  // ===================================================
  // PID
  // ===================================================

  inputTemp = highestTemp;

  targetTempPID = targetTemp;

  myPID.Compute();


  currentFanSpeed =
    constrain(
      max(
        (int)fanOutput,
        MIN_FAN_SPEED
      ),
      MIN_FAN_SPEED,
      255
    );


  analogWrite(
    FAN_PIN,
    currentFanSpeed
  );


  // Wenn SD okay ist, Error LED wieder aus
  if (sdOK) {

    digitalWrite(
      ERROR_LED,
      LOW
    );
  }
}


// =====================================================
// SD-KARTE BESCHREIBEN
// =====================================================

bool writeToSD(String line) {

  if (!sdOK) {

    digitalWrite(
      ERROR_LED,
      HIGH
    );

    return false;
  }


  File file = SD.open(
    dataFilename,
    FILE_WRITE
  );


  if (!file) {

    digitalWrite(
      ERROR_LED,
      HIGH
    );

    return false;
  }


  file.println(line);

  file.flush();

  file.close();


  return true;
}


// =====================================================
// MINUTENMESSUNG
// =====================================================

void logMeasurement() {

  float minutesSinceStart =
    (millis() - experimentStart)
    / 60000.0;


  // ===================================================
  // ZUERST SERIAL MONITOR
  // ===================================================

  Serial.println();

  Serial.println(
    "========================================"
  );

  Serial.print(
    "Time: "
  );

  Serial.print(
    minutesSinceStart,
    2
  );

  Serial.println(
    " min"
  );

  Serial.println();


  // DHT1
  Serial.print("DHT1: ");
  Serial.print(temps[0], 2);
  Serial.print(" C / ");
  Serial.print(hums[0], 2);
  Serial.println(" %");


  // DHT2
  Serial.print("DHT2: ");
  Serial.print(temps[1], 2);
  Serial.print(" C / ");
  Serial.print(hums[1], 2);
  Serial.println(" %");


  // DHT3
  Serial.print("DHT3: ");
  Serial.print(temps[2], 2);
  Serial.print(" C / ");
  Serial.print(hums[2], 2);
  Serial.println(" %");


  // DHT4
  Serial.print("DHT4: ");
  Serial.print(temps[3], 2);
  Serial.print(" C / ");
  Serial.print(hums[3], 2);
  Serial.println(" %");


  Serial.println();


  Serial.print(
    "Fan speed PWM: "
  );

  Serial.println(
    currentFanSpeed
  );


  Serial.print(
    "Target temperature: "
  );

  Serial.print(
    targetTemp,
    0
  );

  Serial.println(
    " C"
  );


  // ===================================================
  // CSV-ZEILE
  // ===================================================

  String line = "";

  line += String(
    minutesSinceStart,
    2
  );


  line += "," + String(temps[0], 2);
  line += "," + String(hums[0], 2);

  line += "," + String(temps[1], 2);
  line += "," + String(hums[1], 2);

  line += "," + String(temps[2], 2);
  line += "," + String(hums[2], 2);

  line += "," + String(temps[3], 2);
  line += "," + String(hums[3], 2);

  line += "," + String(
    currentFanSpeed
  );

  line += "," + String(
    targetTemp,
    0
  );


  // ===================================================
  // SD SPEICHERN
  // ===================================================

  if (writeToSD(line)) {

    Serial.println(
      "Data saved to SD card."
    );
  }

  else {

    Serial.println(
      "ERROR: Data NOT saved to SD card!"
    );
  }


  Serial.println(
    "========================================"
  );
}


// =====================================================
// SETUP
// =====================================================

void setup() {

  Serial.begin(9600);


  // ===================================================
  // LEDS
  // ===================================================

  pinMode(
    STATUS_LED,
    OUTPUT
  );

  pinMode(
    ERROR_LED,
    OUTPUT
  );


  digitalWrite(
    STATUS_LED,
    HIGH
  );


  digitalWrite(
    ERROR_LED,
    LOW
  );


  // ===================================================
  // TASTER
  // ===================================================

  pinMode(
    TEMP_BUTTON_40,
    INPUT_PULLUP
  );

  pinMode(
    TEMP_BUTTON_50,
    INPUT_PULLUP
  );

  pinMode(
    TEMP_BUTTON_60,
    INPUT_PULLUP
  );


  // ===================================================
  // DHT
  // ===================================================

  dht1.begin();
  dht2.begin();
  dht3.begin();
  dht4.begin();


  // ===================================================
  // LÜFTER
  // ===================================================

  pinMode(
    FAN_PIN,
    OUTPUT
  );


  // Lüfter beim Start kurz volle Leistung
  analogWrite(
    FAN_PIN,
    255
  );


  delay(1000);


  currentFanSpeed =
    MIN_FAN_SPEED;


  analogWrite(
    FAN_PIN,
    currentFanSpeed
  );


  // ===================================================
  // PID
  // ===================================================

  myPID.SetMode(
    AUTOMATIC
  );


  myPID.SetOutputLimits(
    MIN_FAN_SPEED,
    255
  );


  // ===================================================
  // SD-KARTE
  // ===================================================

  Serial.println();

  Serial.println(
    "Initializing SD card..."
  );


  if (!SD.begin(SD_CS_PIN)) {

    sdOK = false;


    digitalWrite(
      ERROR_LED,
      HIGH
    );


    Serial.println(
      "ERROR: SD card initialization failed!"
    );
  }

  else {

    sdOK = true;


    Serial.println(
      "SD card initialized successfully."
    );


    createNewFilename();


    Serial.print(
      "Data file: "
    );

    Serial.println(
      dataFilename
    );


    writeToSD(
      "Time_min,"
      "Temp_DHT1_C,"
      "Hum_DHT1_pct,"
      "Temp_DHT2_C,"
      "Hum_DHT2_pct,"
      "Temp_DHT3_C,"
      "Hum_DHT3_pct,"
      "Temp_DHT4_C,"
      "Hum_DHT4_pct,"
      "FanSpeed_PWM,"
      "TargetTemp_C"
    );
  }


  // ===================================================
  // STARTZEIT
  // ===================================================

  experimentStart =
    millis();

  lastSensorRead =
    millis();

  lastLogTime =
    millis();

  lastHeartbeat =
    millis();


  Serial.println();

  Serial.println(
    "========================================"
  );

  Serial.println(
    "LENGKUAS DRYING EXPERIMENT"
  );

  Serial.println(
    "Target temperature at start: 50 C"
  );

  Serial.println(
    "Measurements every 1 minute."
  );

  Serial.println(
    "Serial heartbeat every 10 seconds."
  );

  Serial.println(
    "========================================"
  );


  // ===================================================
  // ERSTE SENSOR-MESSUNG
  // ===================================================

  readDHTSensors();

  controlFan();


  // Erste Messung bei ungefähr 0 Minuten
  logMeasurement();
}


// =====================================================
// LOOP
// =====================================================

void loop() {

  unsigned long now =
    millis();


  // ===================================================
  // TASTER IMMER PRÜFEN
  // ===================================================

  readButtons();


  // ===================================================
  // DHT + LÜFTER ALLE 3 SEKUNDEN
  // ===================================================

  if (
    now - lastSensorRead
    >= SENSOR_INTERVAL
  ) {

    lastSensorRead =
      now;


    readDHTSensors();


    controlFan();
  }


  // ===================================================
  // HEARTBEAT ALLE 10 SEKUNDEN
  //
  // Nur zur Kontrolle, dass Arduino läuft.
  // ===================================================

  if (
    now - lastHeartbeat
    >= HEARTBEAT_INTERVAL
  ) {

    lastHeartbeat =
      now;


    Serial.print(
      "Running... "
    );

    Serial.print(
      (now - experimentStart)
      / 1000
    );

    Serial.println(
      " s"
    );
  }


  // ===================================================
  // JEDE MINUTE AUSGEBEN + SPEICHERN
  // ===================================================

  if (
    now - lastLogTime
    >= LOG_INTERVAL
  ) {

    lastLogTime =
      now;


    logMeasurement();
  }
}