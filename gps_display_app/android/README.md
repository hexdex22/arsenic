# GPS Live — native Android app (Kotlin)

A dependency-free Kotlin app that continuously displays **all** data from
the phone's GPS chip — including things web apps can't see:

- Position (decimal + DMS), horizontal accuracy
- Altitude ± vertical accuracy
- Speed (m/s and km/h) and bearing
- Fix timestamp and count, time-to-first-fix
- **Every visible satellite**: constellation (GPS / GLONASS / Galileo /
  BeiDou / QZSS / SBAS), satellite id, C/N0 signal strength with a bar,
  elevation, azimuth, and whether it is used in the fix
- The **raw NMEA sentences** emitted by the chip, live

The screen stays on while the app is open. Updates are continuous
(every fix, satellite status on every GNSS epoch).

## Get the APK

Every push touching this directory runs the **Build Android APK** GitHub
Actions workflow, which uploads `app-debug.apk` as a run artifact:
repository → Actions → newest "Build Android APK" run → Artifacts.

Install on the phone: download the APK, open it, and allow
"install unknown apps" for your browser/files app when prompted.
(It is a debug-signed APK — fine for personal use, not for the Play Store.)

## Build locally

With Android Studio: open this directory (`gps_display_app/android`)
and Run. With the command line (JDK 17+, Android SDK 34):

```bash
cd gps_display_app/android
gradle assembleDebug   # or ./gradlew if you generate a wrapper
# APK lands in app/build/outputs/apk/debug/app-debug.apk
adb install app/build/outputs/apk/debug/app-debug.apk
```

## Notes

- Min Android 7.0 (API 24); targets Android 14 (API 34).
- Uses `LocationManager` + `GnssStatus` + `OnNmeaMessageListener`
  directly — no Google Play Services, no third-party libraries.
- Location permission is requested on first launch; GPS works best
  outdoors with a clear view of the sky.
