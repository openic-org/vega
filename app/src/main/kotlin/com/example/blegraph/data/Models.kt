package com.example.blegraph.data

import java.time.LocalDateTime

/**
 * Multi-channel time-series point representing data from 4 channels at a single time step.
 * Each 100ms interval contains values for all 4 channels.
 */
data class MultiChannelPoint(
    val channel0: Float,
    val channel1: Float,
    val channel2: Float,
    val channel3: Float,
    val sampleIndex: Long = 0L,  // Sequential sample index from device/simulation
    val timestamp: LocalDateTime = LocalDateTime.now()
) {
    // Helper function to get channel value by index
    fun getChannel(channelIndex: Int): Float = when (channelIndex) {
        0 -> channel0
        1 -> channel1
        2 -> channel2
        3 -> channel3
        else -> throw IndexOutOfBoundsException("Channel index must be 0-3")
    }
}

data class TimeSeriesPoint(
    val value: Float,
    val sampleIndex: Long = 0L,  // Sequential sample index from device/simulation
    val timestamp: LocalDateTime = LocalDateTime.now()
)

data class BluetoothDevice(
    val address: String,
    val name: String?,
    val rssi: Int
)

/**
 * Circular FIFO buffer that maintains exactly [bufferSize] multi-channel data points.
 * When full, new entries replace the oldest (FIFO).
 * Suitable for 10-second time window at 100ms sample rate (100 points).
 * Each point contains 4 channels of data.
 */
class CircularMultiChannelBuffer(val bufferSize: Int = 100) {
    private val buffer = ArrayDeque<MultiChannelPoint>(bufferSize)
    private var nextSampleIndex = 0L
    private var dataPointsReceived = 0L

    fun addPoint(channel0: Float, channel1: Float, channel2: Float, channel3: Float) {
        val point = MultiChannelPoint(
            channel0 = channel0,
            channel1 = channel1,
            channel2 = channel2,
            channel3 = channel3,
            sampleIndex = nextSampleIndex
        )
        
        if (buffer.size >= bufferSize) {
            buffer.removeFirst()  // Remove oldest (FIFO)
        }
        
        buffer.addLast(point)
        nextSampleIndex++
        dataPointsReceived++
    }

    fun getPoints(): List<MultiChannelPoint> = buffer.toList()

    fun clear() {
        buffer.clear()
        nextSampleIndex = 0L
        dataPointsReceived = 0L
    }

    fun size(): Int = buffer.size

    fun isFull(): Boolean = buffer.size >= bufferSize

    fun getTotalPointsReceived(): Long = dataPointsReceived

    /**
     * Extract a single channel as a list of TimeSeriesPoint for graphing
     */
    fun getChannel(channelIndex: Int): List<TimeSeriesPoint> {
        return buffer.map { point ->
            TimeSeriesPoint(
                value = point.getChannel(channelIndex),
                sampleIndex = point.sampleIndex
            )
        }
    }

    /**
     * Extract a single channel with downsampling for visualization performance.
     * Every [downsamplingFactor]'s point is kept.
     * Example: downsamplingFactor=100 means keep 1 point per 100 samples
     */
    fun getChannelDownsampled(channelIndex: Int, downsamplingFactor: Int = 1): List<TimeSeriesPoint> {
        if (downsamplingFactor <= 1) return getChannel(channelIndex)
        
        val result = mutableListOf<TimeSeriesPoint>()
        var sampleCounter = 0
        
        for (point in buffer) {
            if (sampleCounter % downsamplingFactor == 0) {
                result.add(
                    TimeSeriesPoint(
                        value = point.getChannel(channelIndex),
                        sampleIndex = point.sampleIndex
                    )
                )
            }
            sampleCounter++
        }
        
        return result
    }

    /**
     * Extract the last N points of a single channel with optional downsampling.
     * Useful for displaying a specific time window (e.g., last 0.5 seconds or 2 seconds).
     * 
     * @param channelIndex The channel to extract (0-3)
     * @param lastNumPoints How many recent points to include
     * @param downsamplingFactor Downsampling factor (1 = no downsampling, 100 = every 100th point)
     */
    fun getChannelWindow(channelIndex: Int, lastNumPoints: Int, downsamplingFactor: Int = 1): List<TimeSeriesPoint> {
        val startIdx = maxOf(0, buffer.size - lastNumPoints)
        val windowed = buffer.drop(startIdx)
        
        if (downsamplingFactor <= 1) {
            return windowed.map { point ->
                TimeSeriesPoint(
                    value = point.getChannel(channelIndex),
                    sampleIndex = point.sampleIndex
                )
            }
        }
        
        val result = mutableListOf<TimeSeriesPoint>()
        var sampleCounter = 0
        
        for (point in windowed) {
            if (sampleCounter % downsamplingFactor == 0) {
                result.add(
                    TimeSeriesPoint(
                        value = point.getChannel(channelIndex),
                        sampleIndex = point.sampleIndex
                    )
                )
            }
            sampleCounter++
        }
        
        return result
    }
}

/**
 * Legacy single-channel buffer - kept for compatibility if needed
 */
class CircularBuffer(val bufferSize: Int = 100) {
    private val buffer = ArrayDeque<TimeSeriesPoint>(bufferSize)
    private var nextSampleIndex = 0L
    private var dataPointsReceived = 0L

    fun addPoint(value: Float) {
        val point = TimeSeriesPoint(
            value = value,
            sampleIndex = nextSampleIndex
        )
        
        if (buffer.size >= bufferSize) {
            buffer.removeFirst()  // Remove oldest (FIFO)
        }
        
        buffer.addLast(point)
        nextSampleIndex++
        dataPointsReceived++
    }

    fun getPoints(): List<TimeSeriesPoint> = buffer.toList()

    fun clear() {
        buffer.clear()
        nextSampleIndex = 0L
        dataPointsReceived = 0L
    }

    fun size(): Int = buffer.size

    fun isFull(): Boolean = buffer.size >= bufferSize

    fun getTotalPointsReceived(): Long = dataPointsReceived
}
