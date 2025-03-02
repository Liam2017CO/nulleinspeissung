# README – Nulleinspeisung: Python‑Skripte und Node‑RED - Home Assistant Flow

## Überblick

Die Nulleinspeisung-Lösung dient dazu, mithilfe von Messwerten eines Shelly 3EM Pro und der OpenDTU-Daten dynamisch die Leistungsgrenzen (Setpoints) eines bzw. mehrerer Inverter zu regeln. Hierzu gibt es drei unterschiedliche Python‑Skripte (Version 1, 2 und 3) sowie eine Node‑RED‑Implementierung.

- **nulleinspeisungv1.py:**  
  Die erste Version, die grundlegende Funktionalität bietet: Abruf von DTU- und Shelly-Daten, Berechnung der neuen Setpoints und Senden von HTTP‑POST–Befehlen an die DTU.

- **nulleinspeisungv2.py:**  
  Eine erweiterte Version, die bereits detailliertes Logging und grundlegende Fehlerbehandlung implementiert. Hier erfolgt eine modularere Strukturierung der Logik und Konfigurationskonstanten.

- **nulleinspeisungv3.py:**  
  Die weiterentwickelte Version mit noch ausführlicherem Logging (inklusive farblicher Ausgabe und verschiedener Loglevel), verbesserter Fehlerprotokollierung (z. B. bei Timeouts) und der optionalen Integration einer SQLite‑Datenbank zur Speicherung historischer Messwerte.  
  In dieser Version können viele Parameter leichter angepasst werden, um auf spezifische Anforderungen einzugehen.

- **Node‑RED Flow (nulleinspeisung.json):**  
  Die Node‑RED‑Version repliziert die Funktionalität der Python‑Skripte in einer visuell programmierbaren Umgebung. Der Flow pollt regelmäßig die DTU‑ und Shelly‑Endpunkte, berechnet die Setpoints für Inverter 1 und 2 und sendet die entsprechenden HTTP‑POST‑Befehle an die DTU. Die Ergebnisse (z. B. berechnete Setpoints) werden im Debug–Panel ausgegeben und können bei Bedarf in Home Assistant integriert werden.

---

## Konfiguration und Anpassungsmöglichkeiten

### Gemeinsame Konfigurationselemente (für alle Python‑Skripte)

Alle Versionen basieren auf den gleichen Grundkonzepten und nutzen folgende Konfigurationsparameter, die direkt im Code als Konstanten definiert sind:

- **SERIAL / serial:**  
  Seriennummer des primären Inverters (z. B. `"116492226387"`).

- **MAXIMUM_WR / maximum_wr und MINIMUM_WR / minimum_wr:**  
  Maximale und minimale Leistung (z. B. 2000 W bzw. 200 W) für den ersten Inverter.

- **ENABLE_SECOND_INVERTER / enable_second_inverter:**  
  Flag zur Aktivierung des zweiten Inverters.

- **SERIAL2 / serial2:**  
  Seriennummer des zweiten Inverters (z. B. `"1164a00b64e3"`).

- **MAXIMUM_WR2 / maximum_wr2 und MINIMUM_WR2 / minimum_wr2:**  
  Maximale und minimale Leistung für den zweiten Inverter (z. B. 1500 W bzw. 200 W).

- **DEFAULT_ALTES_LIMIT2 / default_altes_limit2:**  
  Fallback-Wert, falls keine aktuellen Daten für den zweiten Inverter verfügbar sind.

- **DTU_IP, DTU_NUTZER, DTU_PASSWORT:**  
  Zugangsdaten für die OpenDTU (z. B. IP-Adresse, Benutzername, Passwort).

- **SHELLY_IP:**  
  IP-Adresse des Shelly 3EM Pro.

**Anpassung:**  
Diese Parameter müssen im jeweiligen Skript (am Anfang bzw. in einem Konfigurationsblock) an deine Gegebenheiten angepasst werden. Eine dynamischere Konfiguration (z. B. über externe Konfigurationsdateien oder Umgebungsvariablen) kann in zukünftigen Erweiterungen implementiert werden.

### Unterschiede zwischen den Python‑Versionen

- **nulleinspeisungv1.py:**  
  - Grundlegende Funktionalität: Abruf der Live-Daten von DTU und Shelly, Berechnung der neuen Setpoints und Senden der Konfigurationsbefehle.  
  - Einfaches Logging (meist über `print()` oder Basis-Logging).

- **nulleinspeisungv2.py:**  
  - Handling von 2 Invertern  
  - Erweiterte Logik mit modularerer Code-Struktur und zusätzlicher Fehlerbehandlung.  
  - Detaillierteres Logging (z. B. mit verschiedenen Loglevels) als in v1.

- **nulleinspeisungv3.py:**  
  - Noch ausführlicheres Logging (inklusive farblicher Darstellung und ausführlichen Fehlermeldungen).  
  - Verbesserte Fehlerprotokollierung (z. B. bei Verbindungsproblemen/Timeouts).  
  - Optionaler Einsatz einer SQLite‑Datenbank, um Messwerte historisch zu speichern und später auszuwerten.  
  - Leichtere Erweiterbarkeit und Wartbarkeit durch einen modulareren Aufbau.

### Node‑RED Flow (nulleinspeisung.json)

Der Node‑RED Flow implementiert die gleiche Funktionalität wie die Python‑Skripte, jedoch in einer grafischen Umgebung:

- **Poll-Mechanismus:**  
  Ein Inject Node löst alle 10 Sekunden den Abruf der DTU‑ und Shelly‑Daten aus.

- **HTTP Request Nodes:**  
  Rufen die Daten von den entsprechenden Endpunkten ab.  
  (Hier können URL und Authentifizierungsdaten direkt in den Nodes konfiguriert werden.)

- **Change Nodes:**  
  Setzen das `msg.topic`, damit der Join Node die eingehenden Nachrichten korrekt zusammenführt.

- **Join Node:**  
  Vereinigt die zwei eingehenden Nachrichten (eine von DTU, eine von Shelly) zu einem Objekt, anhand des gesetzten `msg.topic`.

- **Function Node ("Compute Setpoints"):**  
  Rechnet auf Basis der empfangenen Daten die neuen Setpoints für Inverter 1 und Inverter 2 aus.  
  Feste Parameter wie maximale/minimale Werte sind hier im Code hinterlegt, können jedoch direkt in der Funktion angepasst werden.

- **HTTP POST Nodes:**  
  Senden die berechneten Setpoints an die DTU, um die Inverterlimits zu aktualisieren.

- **Debug Nodes:**  
  Zeigen die berechneten Werte und die Antworten der POST‑Anfragen an.

**Anpassung:**  
Alle Konfigurationsparameter (URLs, Limits, etc.) können direkt in den Nodes angepasst werden. Für eine dynamischere Lösung können diese Werte auch über Umgebungsvariablen oder globale Kontextvariablen gesteuert werden.

---

## Zusammenfassung

- **Python‑Skripte:**  
  Bieten eine direkte, skriptbasierte Lösung zur Steuerung der Inverter über Abruf der DTU‑ und Shelly‑Daten, Berechnung der Setpoints und Senden von Updates.  
  - **v1:** Basisversion  
  - **v2:** Erweiterte Logik und Fehlerbehandlung (inkl. Handling von 2 Invertern)  
  - **v3:** Ausführliches Logging, verbesserte Fehlerprotokollierung und optionale Speicherung in einer SQLite‑Datenbank  
    - _to-dos:_ Die korrekte Ausgabe der aktuellen Leistung je Inverter bei mehr als einem Inverter

- **Node‑RED Flow (nulleinspeisung.json):**  
  Repliziert die Funktionalität der Python‑Skripte in einer visuell programmierten Umgebung, die sich gut für schnelle Anpassungen und die Integration in Home Assistant eignet.

Beide Ansätze erfüllen denselben Zweck – du kannst je nach deinen Vorlieben und der Systemumgebung entscheiden, ob du die Python‑Skripte oder den Node‑RED Flow einsetzt.
