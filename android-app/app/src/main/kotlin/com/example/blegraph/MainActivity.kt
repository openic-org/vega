package com.example.blegraph

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.ui.Modifier
import com.example.blegraph.ble.BleManager
import com.example.blegraph.ui.BleGraphScreen
import com.example.blegraph.ui.theme.BLEGraphTheme
import com.example.blegraph.vm.BleGraphViewModel

class MainActivity : ComponentActivity() {
    private lateinit var bleManager: BleManager
    private lateinit var viewModel: BleGraphViewModel

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        bleManager = BleManager(this)
        viewModel = BleGraphViewModel(bleManager)

        setContent {
            BLEGraphTheme {
                Surface(
                    modifier = Modifier.fillMaxSize(),
                    color = MaterialTheme.colorScheme.background
                ) {
                    BleGraphScreen(viewModel)
                }
            }
        }
    }
}
