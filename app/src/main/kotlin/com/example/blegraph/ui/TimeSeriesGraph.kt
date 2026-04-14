package com.example.blegraph.ui

import android.graphics.Paint
import android.graphics.Typeface
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.drawscope.DrawScope
import androidx.compose.ui.graphics.nativeCanvas
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.example.blegraph.data.TimeSeriesPoint

/**
 * Fixed-window time-series graph.
 *
 * The x-axis always spans exactly [windowDurationSec] seconds. Data is right-anchored:
 * the most-recent sample is at the right edge. Before the buffer fills the window, the
 * signal appears on the right and blank space is on the left (oscilloscope-style).
 *
 * X positions are derived from [TimeSeriesPoint.timestampUs] (µs since MCU boot).
 * Y positions are auto-scaled to the visible data with a 5 % margin so peaks never
 * touch the axis lines. Five labelled tick marks show the actual ADC values.
 *
 * @param dataPoints        Points to render (already windowed + decimated by BleManager).
 * @param channelName       Label drawn above the graph.
 * @param lineColor         Waveform color.
 * @param windowDurationSec Width of the visible time window in seconds (e.g. 0.3 or 3.0).
 */
@Composable
fun TimeSeriesGraph(
    dataPoints: List<TimeSeriesPoint>,
    channelName: String = "Signal",
    lineColor: Color = Color.Blue,
    windowDurationSec: Float,
    modifier: Modifier = Modifier
) {
    val windowDurationUs = (windowDurationSec * 1_000_000f).toLong().coerceAtLeast(1L)

    // Reused across frames — created once per composition site.
    val yLabelPaint = remember {
        Paint().apply {
            color     = android.graphics.Color.DKGRAY
            textSize  = 14f
            textAlign = Paint.Align.RIGHT
            isAntiAlias = true
            typeface  = Typeface.MONOSPACE
        }
    }

    Column(modifier = modifier.fillMaxSize()) {
        // Channel label
        Text(
            text = channelName,
            style = MaterialTheme.typography.labelMedium,
            modifier = Modifier.padding(start = 16.dp, top = 4.dp)
        )

        // Graph canvas
        Box(
            modifier = Modifier
                .fillMaxWidth()
                .weight(1f)
                .background(Color.White)
                .padding(horizontal = 8.dp, vertical = 4.dp)
        ) {
            Canvas(
                modifier = Modifier
                    .fillMaxSize()
                    .background(Color(0xFFF5F5F5))
            ) {
                val w = size.width
                val h = size.height

                // Asymmetric padding: left is wider to accommodate y-axis labels.
                val leftPad  = 64f
                val rightPad = 12f
                val vPad     = 20f
                val plotW = w - leftPad - rightPad
                val plotH = h - 2 * vPad

                drawGrid(leftPad, rightPad, vPad, w, h)

                // Axes
                drawLine(Color.Black, Offset(leftPad, vPad),     Offset(leftPad, h - vPad), strokeWidth = 2f)
                drawLine(Color.Black, Offset(leftPad, h - vPad), Offset(w - rightPad, h - vPad), strokeWidth = 2f)

                // X-axis tick marks (5 evenly-spaced)
                val numXTicks = 5
                for (i in 0 until numXTicks) {
                    val x = leftPad + (i.toFloat() / (numXTicks - 1)) * plotW
                    drawLine(Color.Gray, Offset(x, h - vPad), Offset(x, h - vPad + 5f), strokeWidth = 1f)
                }

                if (dataPoints.size < 2) {
                    // Draw unlabelled y-ticks even when there's no data yet
                    for (i in 0..4) {
                        val y = h - vPad - (i / 4f) * plotH
                        drawLine(Color.Gray, Offset(leftPad - 5f, y), Offset(leftPad, y), strokeWidth = 1f)
                    }
                    return@Canvas
                }

                // ── Y-scale ──────────────────────────────────────────────────
                // Auto-fit to visible data + 5 % vertical margin so peaks/troughs
                // never fall exactly on the axis lines.
                val rawMin = dataPoints.minOf { it.value }
                val rawMax = dataPoints.maxOf { it.value }
                val rawRange = if (rawMax == rawMin) 1f else rawMax - rawMin
                val margin   = rawRange * 0.05f
                val yMin     = rawMin - margin
                val yMax     = rawMax + margin
                val yRange   = yMax - yMin

                // ── X-scale ──────────────────────────────────────────────────
                val lastUs  = dataPoints.last().timestampUs
                val firstUs = lastUs - windowDurationUs

                fun timestampToX(us: Long): Float =
                    leftPad + ((us - firstUs).toFloat() / windowDurationUs) * plotW

                fun valueToY(v: Float): Float =
                    h - vPad - ((v - yMin) / yRange) * plotH

                // ── Y-axis ticks + labels ─────────────────────────────────────
                val numYTicks = 5
                drawContext.canvas.nativeCanvas.apply {
                    for (i in 0 until numYTicks) {
                        val frac  = i.toFloat() / (numYTicks - 1)
                        val y     = h - vPad - frac * plotH
                        val value = yMin + frac * yRange

                        // Tick mark
                        drawLine(
                            Color.Gray,
                            Offset(leftPad - 5f, y),
                            Offset(leftPad, y),
                            strokeWidth = 1f
                        )

                        // Label (right-aligned, vertically centred on the tick)
                        drawText(
                            formatYLabel(value),
                            leftPad - 8f,
                            y + yLabelPaint.textSize * 0.35f,
                            yLabelPaint
                        )
                    }
                }

                // ── Waveform ──────────────────────────────────────────────────
                for (i in 0 until dataPoints.size - 1) {
                    val x1 = timestampToX(dataPoints[i].timestampUs)
                    val y1 = valueToY(dataPoints[i].value)
                    val x2 = timestampToX(dataPoints[i + 1].timestampUs)
                    val y2 = valueToY(dataPoints[i + 1].value)
                    if (x2 < leftPad || x1 > w - rightPad) continue
                    drawLine(lineColor, Offset(x1, y1), Offset(x2, y2), strokeWidth = 2f)
                }
            }
        }

        // X-axis time labels: 0.0 s (left edge) → windowDurationSec (right edge)
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .height(16.dp)
                .background(Color.White)
                .padding(start = (8 + 4).dp, end = 8.dp),   // align with leftPad offset
            horizontalArrangement = Arrangement.SpaceBetween
        ) {
            val numLabels = 5
            val fmt = if (windowDurationSec >= 1f) "%.1fs" else "%.2fs"
            for (i in 0 until numLabels) {
                val timeSec = (i.toFloat() / (numLabels - 1)) * windowDurationSec
                Text(
                    text = fmt.format(timeSec),
                    style = MaterialTheme.typography.labelSmall,
                    fontSize = 9.sp
                )
            }
        }
    }
}

// ── Helpers ───────────────────────────────────────────────────────────────────

/**
 * Format a y-axis tick value compactly.
 * Uses "k" suffix for |value| ≥ 10 000 to keep labels narrow.
 */
private fun formatYLabel(value: Float): String = when {
    kotlin.math.abs(value) >= 10_000f -> "%.1fk".format(value / 1_000f)
    else                               -> "%.0f".format(value)
}

private fun DrawScope.drawGrid(
    leftPad: Float, rightPad: Float, vPad: Float,
    width: Float, height: Float
) {
    val gridSpacing = 50f
    var x = leftPad
    while (x <= width - rightPad) {
        drawLine(Color.LightGray, Offset(x, vPad), Offset(x, height - vPad), strokeWidth = 0.5f)
        x += gridSpacing
    }
    var y = vPad
    while (y <= height - vPad) {
        drawLine(Color.LightGray, Offset(leftPad, y), Offset(width - rightPad, y), strokeWidth = 0.5f)
        y += gridSpacing
    }
}
