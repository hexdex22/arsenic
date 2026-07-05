package com.gpsdisplay.live

import android.Manifest
import android.app.Activity
import android.content.Context
import android.content.pm.PackageManager
import android.location.GnssStatus
import android.location.Location
import android.location.LocationListener
import android.location.LocationManager
import android.location.OnNmeaMessageListener
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.view.WindowManager
import android.widget.TextView
import java.text.SimpleDateFormat
import java.util.ArrayDeque
import java.util.Date
import java.util.Locale
import kotlin.math.abs
import kotlin.math.floor
import kotlin.math.roundToInt

/**
 * Continuously displays all data from the phone's GPS chip:
 * position, altitude, accuracy, speed, bearing, fix time, every visible
 * satellite (constellation, id, C/N0, elevation, azimuth, used-in-fix),
 * and the raw NMEA sentences the chip emits.
 */
class MainActivity : Activity() {

    private lateinit var locationManager: LocationManager
    private val handler = Handler(Looper.getMainLooper())
    private val nmeaLog = ArrayDeque<String>()
    private var fixCount = 0
    private var listening = false

    private val timeFormat = SimpleDateFormat("HH:mm:ss", Locale.US)

    private val locationListener = LocationListener { location ->
        fixCount += 1
        renderLocation(location)
    }

    private val gnssCallback = object : GnssStatus.Callback() {
        override fun onSatelliteStatusChanged(status: GnssStatus) {
            renderSatellites(status)
        }
        override fun onFirstFix(ttffMillis: Int) {
            statusView.text = "First fix after ${ttffMillis / 1000.0} s"
        }
    }

    private val nmeaListener = OnNmeaMessageListener { message, _ ->
        val line = message.trim()
        if (line.isNotEmpty()) {
            if (nmeaLog.size >= 12) nmeaLog.removeFirst()
            nmeaLog.addLast(line)
            nmeaView.text = nmeaLog.joinToString("\n")
        }
    }

    private lateinit var statusView: TextView
    private lateinit var positionView: TextView
    private lateinit var satellitesView: TextView
    private lateinit var nmeaView: TextView

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)

        statusView = findViewById(R.id.status)
        positionView = findViewById(R.id.position)
        satellitesView = findViewById(R.id.satellites)
        nmeaView = findViewById(R.id.nmea)
        locationManager = getSystemService(Context.LOCATION_SERVICE) as LocationManager

        statusView.setOnClickListener { ensurePermissionAndStart() }
    }

    override fun onResume() {
        super.onResume()
        ensurePermissionAndStart()
    }

    override fun onPause() {
        super.onPause()
        stopListening()
    }

    private fun ensurePermissionAndStart() {
        if (checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION)
            == PackageManager.PERMISSION_GRANTED
        ) {
            startListening()
        } else {
            requestPermissions(arrayOf(Manifest.permission.ACCESS_FINE_LOCATION), 1)
        }
    }

    override fun onRequestPermissionsResult(
        requestCode: Int,
        permissions: Array<out String>,
        grantResults: IntArray,
    ) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (grantResults.firstOrNull() == PackageManager.PERMISSION_GRANTED) {
            startListening()
        } else {
            statusView.text = getString(R.string.need_permission)
        }
    }

    private fun startListening() {
        if (listening) return
        try {
            if (!locationManager.isProviderEnabled(LocationManager.GPS_PROVIDER)) {
                statusView.text = "GPS is turned off — enable Location in settings."
                return
            }
            locationManager.requestLocationUpdates(
                LocationManager.GPS_PROVIDER, 1000L, 0f, locationListener
            )
            locationManager.registerGnssStatusCallback(gnssCallback, handler)
            locationManager.addNmeaListener(nmeaListener, handler)
            listening = true
            statusView.text = getString(R.string.waiting)
        } catch (e: SecurityException) {
            statusView.text = getString(R.string.need_permission)
        }
    }

    private fun stopListening() {
        if (!listening) return
        locationManager.removeUpdates(locationListener)
        locationManager.unregisterGnssStatusCallback(gnssCallback)
        locationManager.removeNmeaListener(nmeaListener)
        listening = false
    }

    private fun renderLocation(location: Location) {
        statusView.text = "Live — $fixCount fixes"
        val sb = StringBuilder()
        sb.append("Lat  %.6f   %s\n".format(location.latitude, dms(location.latitude, "N", "S")))
        sb.append("Lon  %.6f  %s\n".format(location.longitude, dms(location.longitude, "E", "W")))
        sb.append("Acc  ± %.1f m\n".format(location.accuracy))
        if (location.hasAltitude()) {
            val vertical =
                if (Build.VERSION.SDK_INT >= 26 && location.hasVerticalAccuracy())
                    "  ± %.1f m".format(location.verticalAccuracyMeters)
                else ""
            sb.append("Alt  %.1f m%s\n".format(location.altitude, vertical))
        } else {
            sb.append("Alt  ---\n")
        }
        if (location.hasSpeed()) {
            sb.append(
                "Spd  %.1f m/s  (%.1f km/h)\n".format(location.speed, location.speed * 3.6f)
            )
        } else {
            sb.append("Spd  ---\n")
        }
        if (location.hasBearing()) {
            sb.append("Brg  %.1f°\n".format(location.bearing))
        } else {
            sb.append("Brg  ---\n")
        }
        sb.append("Fix  ${timeFormat.format(Date(location.time))} (device clock offset excluded)")
        positionView.text = sb.toString()
    }

    private fun renderSatellites(status: GnssStatus) {
        val rows = (0 until status.satelliteCount).map { i ->
            SatRow(
                system = constellationName(status.getConstellationType(i)),
                svid = status.getSvid(i),
                cn0 = status.getCn0DbHz(i),
                elevation = status.getElevationDegrees(i),
                azimuth = status.getAzimuthDegrees(i),
                used = status.usedInFix(i),
            )
        }.sortedWith(compareBy({ it.system }, { it.svid }))

        val used = rows.count { it.used }
        val sb = StringBuilder()
        sb.append("${rows.size} in view, $used used in fix  (* = used)\n\n")
        sb.append("SYS      ID  C/N0  ELEV   AZIM\n")
        for (row in rows) {
            val bar = "#".repeat((row.cn0 / 3).roundToInt().coerceIn(0, 18))
            sb.append(
                "%-7s %3d %5.1f %5.0f° %6.0f° %s %s\n".format(
                    row.system, row.svid, row.cn0,
                    row.elevation, row.azimuth,
                    if (row.used) "*" else " ", bar,
                )
            )
        }
        satellitesView.text = sb.toString()
    }

    private data class SatRow(
        val system: String,
        val svid: Int,
        val cn0: Float,
        val elevation: Float,
        val azimuth: Float,
        val used: Boolean,
    )

    private fun constellationName(type: Int): String = when (type) {
        GnssStatus.CONSTELLATION_GPS -> "GPS"
        GnssStatus.CONSTELLATION_SBAS -> "SBAS"
        GnssStatus.CONSTELLATION_GLONASS -> "GLONASS"
        GnssStatus.CONSTELLATION_QZSS -> "QZSS"
        GnssStatus.CONSTELLATION_BEIDOU -> "BeiDou"
        GnssStatus.CONSTELLATION_GALILEO -> "Galileo"
        else -> "Other"
    }

    private fun dms(value: Double, positive: String, negative: String): String {
        val hemisphere = if (value >= 0) positive else negative
        val abs = abs(value)
        val degrees = floor(abs).toInt()
        val minutesFloat = (abs - degrees) * 60.0
        val minutes = floor(minutesFloat).toInt()
        val seconds = (minutesFloat - minutes) * 60.0
        return "%d°%d'%.1f\" %s".format(degrees, minutes, seconds, hemisphere)
    }
}
