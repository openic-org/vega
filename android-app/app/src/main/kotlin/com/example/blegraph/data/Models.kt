package com.example.blegraph.data

/**
 * Multi-channel time-series point representing data from 4 channels at a single time step.
 *
 * @param timestampUs  Microseconds since MCU boot (from the STM32 HAL_GetTick timestamp).
 */
data class MultiChannelPoint(
    val channel0: Float,
    val channel1: Float,
    val channel2: Float,
    val channel3: Float,
    val timestampUs: Long
) {
    fun getChannel(channelIndex: Int): Float = when (channelIndex) {
        0 -> channel0
        1 -> channel1
        2 -> channel2
        3 -> channel3
        else -> throw IndexOutOfBoundsException("Channel index must be 0-3")
    }
}

/**
 * Single-channel point for graphing.
 *
 * @param timestampUs  Microseconds since MCU boot, matching [MultiChannelPoint.timestampUs].
 */
data class TimeSeriesPoint(
    val value: Float,
    val timestampUs: Long
)

data class BluetoothDevice(
    val address: String,
    val name: String?,
    val rssi: Int
)

/**
 * Thread-safe circular FIFO buffer for multi-channel time-series data.
 *
 * Written from the BLE parser coroutine (Dispatchers.Default) and read / cleared
 * from the Main thread (UI refresh, disconnect). Every public method is
 * @Synchronized on `this` to prevent concurrent modification — in particular the
 * NPE that occurs when [clear] nulls the backing array while [getChannelWindow]
 * is mid-iteration.
 */
class CircularMultiChannelBuffer(val bufferSize: Int = 100) {
    private val buffer = ArrayDeque<MultiChannelPoint>(bufferSize)
    private var dataPointsReceived = 0L

    @Synchronized
    fun addPoint(channel0: Float, channel1: Float, channel2: Float, channel3: Float, timestampUs: Long) {
        if (buffer.size >= bufferSize) buffer.removeFirst()
        buffer.addLast(MultiChannelPoint(channel0, channel1, channel2, channel3, timestampUs))
        dataPointsReceived++
    }

    @Synchronized
    fun getPoints(): List<MultiChannelPoint> = buffer.toList()

    @Synchronized
    fun clear() {
        buffer.clear()
        dataPointsReceived = 0L
    }

    @Synchronized
    fun size(): Int = buffer.size

    @Synchronized
    fun isFull(): Boolean = buffer.size >= bufferSize

    @Synchronized
    fun getTotalPointsReceived(): Long = dataPointsReceived

    /** Extract a single channel as a list of [TimeSeriesPoint] for graphing. */
    @Synchronized
    fun getChannel(channelIndex: Int): List<TimeSeriesPoint> {
        return buffer.map { point ->
            TimeSeriesPoint(point.getChannel(channelIndex), point.timestampUs)
        }
    }

    /**
     * Extract a single channel with downsampling.
     * Every [downsamplingFactor]-th point is kept.
     */
    @Synchronized
    fun getChannelDownsampled(channelIndex: Int, downsamplingFactor: Int = 1): List<TimeSeriesPoint> {
        if (downsamplingFactor <= 1) return getChannel(channelIndex)
        val result = mutableListOf<TimeSeriesPoint>()
        buffer.forEachIndexed { i, point ->
            if (i % downsamplingFactor == 0) {
                result.add(TimeSeriesPoint(point.getChannel(channelIndex), point.timestampUs))
            }
        }
        return result
    }

    /**
     * Extract the last [lastNumPoints] of a single channel with optional downsampling.
     *
     * @param channelIndex       Channel to extract (0–3).
     * @param lastNumPoints      How many recent points to consider.
     * @param downsamplingFactor Keep every Nth point (1 = no downsampling).
     */
    @Synchronized
    fun getChannelWindow(channelIndex: Int, lastNumPoints: Int, downsamplingFactor: Int = 1): List<TimeSeriesPoint> {
        val startIdx = maxOf(0, buffer.size - lastNumPoints)

        if (downsamplingFactor <= 1) {
            val result = ArrayList<TimeSeriesPoint>(buffer.size - startIdx)
            for (i in startIdx until buffer.size) {
                val point = buffer[i]
                result.add(TimeSeriesPoint(point.getChannel(channelIndex), point.timestampUs))
            }
            return result
        }

        val result = mutableListOf<TimeSeriesPoint>()
        var sampleCounter = 0
        for (i in startIdx until buffer.size) {
            if (sampleCounter % downsamplingFactor == 0) {
                val point = buffer[i]
                result.add(TimeSeriesPoint(point.getChannel(channelIndex), point.timestampUs))
            }
            sampleCounter++
        }
        return result
    }
}

/**
 * Legacy single-channel buffer — kept for compatibility.
 * Uses a sequential counter as a stand-in timestamp (1 count = 1 µs at 1 MHz, or just an index).
 */
class CircularBuffer(val bufferSize: Int = 100) {
    private val buffer = ArrayDeque<TimeSeriesPoint>(bufferSize)
    private var nextIndex = 0L
    private var dataPointsReceived = 0L

    fun addPoint(value: Float) {
        if (buffer.size >= bufferSize) buffer.removeFirst()
        buffer.addLast(TimeSeriesPoint(value, nextIndex))
        nextIndex++
        dataPointsReceived++
    }

    fun getPoints(): List<TimeSeriesPoint> = buffer.toList()

    fun clear() {
        buffer.clear()
        nextIndex = 0L
        dataPointsReceived = 0L
    }

    fun size(): Int = buffer.size

    fun isFull(): Boolean = buffer.size >= bufferSize

    fun getTotalPointsReceived(): Long = dataPointsReceived
}
