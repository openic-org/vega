package com.example.blegraph.ui

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.drawscope.DrawScope
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.example.blegraph.data.TimeSeriesPoint

@Composable
fun TimeSeriesGraph(
    dataPoints: List<TimeSeriesPoint>,
    channelName: String = "Signal",
    lineColor: Color = Color.Blue,
    modifier: Modifier = Modifier
) {
    Column(
        modifier = modifier.fillMaxSize()
    ) {
        // Channel name label
        Text(
            text = channelName,
            style = MaterialTheme.typography.labelMedium,
            modifier = Modifier.padding(start = 16.dp, top = 8.dp)
        )
        
        Box(
            modifier = Modifier
                .fillMaxWidth()
                .weight(1f)
                .background(Color.White)
                .padding(16.dp)
        ) {
            Canvas(
                modifier = Modifier
                    .fillMaxSize()
                    .background(Color(0xFFF5F5F5))
            ) {
                if (dataPoints.isEmpty()) return@Canvas

                val width = size.width
                val height = size.height
                val padding = 40f

                // Draw background grid
                drawGrid(padding, width, height)

                // Calculate min and max values
                val minValue = dataPoints.minOf { it.value }
                val maxValue = dataPoints.maxOf { it.value }
                val valueRange = if (maxValue == minValue) 1f else maxValue - minValue

                // Draw axes
                // Y-axis
                drawLine(
                    color = Color.Black,
                    start = Offset(padding, padding),
                    end = Offset(padding, height - padding),
                    strokeWidth = 2f
                )

                // X-axis
                drawLine(
                    color = Color.Black,
                    start = Offset(padding, height - padding),
                    end = Offset(width - padding, height - padding),
                    strokeWidth = 2f
                )

                // Draw data points and line
                val pointSpacing = (width - 2 * padding) / (dataPoints.size - 1).coerceAtLeast(1)
                
                // Skip drawing circles for very dense data (more than 1000 points)
                // to reduce rendering overhead. Lines are sufficient for visualization.
                val shouldDrawCircles = dataPoints.size <= 1000

                for (i in 0 until dataPoints.size - 1) {
                    val current = dataPoints[i]
                    val next = dataPoints[i + 1]

                    val x1 = padding + i * pointSpacing
                    val y1 = height - padding - ((current.value - minValue) / valueRange) * (height - 2 * padding)

                    val x2 = padding + (i + 1) * pointSpacing
                    val y2 = height - padding - ((next.value - minValue) / valueRange) * (height - 2 * padding)

                    // Draw line between points
                    drawLine(
                        color = lineColor,
                        start = Offset(x1, y1),
                        end = Offset(x2, y2),
                        strokeWidth = 2f
                    )
                }

                // Draw circles only if not too dense
                if (shouldDrawCircles) {
                    for (i in dataPoints.indices) {
                        val point = dataPoints[i]
                        val x = padding + i * pointSpacing
                        val y = height - padding - ((point.value - minValue) / valueRange) * (height - 2 * padding)

                        drawCircle(
                            color = lineColor,
                            radius = 3f,
                            center = Offset(x, y)
                        )
                    }
                }

                // Draw Y-axis labels
                for (i in 0..4) {
                    val value = minValue + (i / 4f) * valueRange
                    val y = height - padding - (i / 4f) * (height - 2 * padding)

                    drawLine(
                        color = Color.Gray,
                        start = Offset(padding - 5f, y),
                        end = Offset(padding, y),
                        strokeWidth = 1f
                    )
                }

                // Draw X-axis time labels
                if (dataPoints.isNotEmpty()) {
                    val numLabels = 5
                    for (i in 0 until numLabels) {
                        val index = (i * dataPoints.size / (numLabels - 1)).coerceAtMost(dataPoints.size - 1)
                        val x = padding + index * pointSpacing
                        val textY = height - padding + 20f

                        // Draw tick mark
                        drawLine(
                            color = Color.Gray,
                            start = Offset(x, height - padding),
                            end = Offset(x, height - padding + 5f),
                            strokeWidth = 1f
                        )
                    }
                }
            }
        }

        // X-axis time labels below the graph
        if (dataPoints.isNotEmpty()) {
            Box(
                modifier = Modifier
                    .fillMaxWidth()
                    .height(40.dp)
                    .background(Color.White)
                    .padding(vertical = 4.dp)
            ) {
                androidx.compose.foundation.layout.Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = androidx.compose.foundation.layout.Arrangement.SpaceBetween
                ) {
                    val numLabels = 5
                    for (i in 0 until numLabels) {
                        val index = (i * dataPoints.size / (numLabels - 1)).coerceAtMost(dataPoints.size - 1)
                        val sampleIndex = dataPoints[index].sampleIndex
                        val timeSeconds = sampleIndex * 0.1  // 100ms per sample
                        Text(
                            text = String.format("%.1fs", timeSeconds),
                            style = MaterialTheme.typography.labelSmall,
                            fontSize = 10.sp,
                            modifier = Modifier.padding(horizontal = 8.dp)
                        )
                    }
                }
            }
        }
    }
}

private fun DrawScope.drawGrid(padding: Float, width: Float, height: Float) {
    val gridSpacing = 50f
    val strokeWidth = 0.5f

    // Vertical grid lines
    var x = padding
    while (x < width - padding) {
        drawLine(
            color = Color.LightGray,
            start = Offset(x, padding),
            end = Offset(x, height - padding),
            strokeWidth = strokeWidth
        )
        x += gridSpacing
    }

    // Horizontal grid lines
    var y = padding
    while (y < height - padding) {
        drawLine(
            color = Color.LightGray,
            start = Offset(padding, y),
            end = Offset(width - padding, y),
            strokeWidth = strokeWidth
        )
        y += gridSpacing
    }
}
