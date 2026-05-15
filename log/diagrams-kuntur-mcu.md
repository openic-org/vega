# Kuntur MCU — Architecture Diagrams

Paste each code block at https://mermaid.live to render.

---

## Diagram 1 — Startup & BLE Connection

```mermaid
flowchart TD
    A[POWER ON] --> B["SystemClock_Config\nRC64MPLL DIV1 = 64 MHz SYSCLK\nFLASH_WAIT_STATES_1"]
    B --> C["HAL init: RTC BYPSHAD=1\nLSE 32.768 kHz\nUSART1 115200 on PA1"]
    C --> D["FPGA_SPI_Init\nPB3=SCK  PA8=MISO\nPA11=MOSI  PA9=NSS\noverrides SPI3 AF pins on APB0"]
    D --> E["MX_APPE_Init\nBLE stack + GATT init\nSTREAM_APP_Init  DIS_Init"]
    E --> F["HAL_Delay 5000 ms\nSWD attach window\nprints 'starting...' on USART1"]
    F --> G["BLE advertising starts\nname = Kuntur-Headstage\nfast 80-100 ms interval\nLP VTIMER after 60 s"]
    G --> H{Phone connects?}
    H -->|no| G
    H -->|yes| I["connection_complete_event\nconn_handle saved\nATT_MTU = 247"]
    I --> J["hci_le_set_data_length\nTxOctets=251  TxTime=2120\nDLE extension request\nsequential: PHY must wait"]
    J --> K{"DATA_LENGTH_CHANGE\nMaxTxOctets=251?"}
    K -->|not yet| J
    K -->|confirmed| L["hci_le_set_phy\nALL_PHYS=0\nTX=LE_2M  RX=LE_2M"]
    L --> M{"LE_PHY_UPDATE event\nTxPhy=2?"}
    M -->|"2M confirmed"| O["2M PHY active\n~2 Mbps raw bitrate"]
    M -->|"1M — peer declined or unsupported\nno retry: firmware accepts 1M\nand continues normally"| O
    O --> P["STREAM_EventHandler waits for\nCCCD write on handle\nStreamNotifyCharHdle+2\nuuid 0xFFF2 CCCD"]
    P --> Q{"CCCD value\n= 0x0001?"}
    Q -->|0x0000 disabled| P
    Q -->|0x0001 enabled| R["STREAM_APP_OnCCCDWrite\ns_cccd_enabled = 1\nconn_handle saved to stream_app"]
    R --> S["HAL_VTIMER_StartTimerMs\nsend_timer period = STREAM_SEND_PERIOD_MS = 2 ms\nStreamSendTimerCb callback"]
    S --> T["StreamSendTimerCb fires\nUTIL_SEQ_SetTask\nCFG_TASK_STREAM_SEND_ID bit5 PRIO_1\nrescheduled every 2 ms"]
    T --> U[StreamSendTask — see diagram 2]
```

---

## Diagram 2 — FPGA SPI Acquisition (StreamSendTask tight loop)

```mermaid
flowchart TD
    A["StreamSendTask\nUTIL_SEQ dispatches bit5 PRIO_1"] --> B{"s_cccd_enabled\nand conn valid?"}
    B -->|no| C[return — idle]
    B -->|yes| D["Build StreamDataPacket_t header\ntimestamp_s  = H*3600 + M*60 + S\ntimestamp_sub_s = 32767-SSR * 32000/32768\nseq_num = seq_num++ mod 256\nnum_pairs = STREAM_PAIRS_PER_PACKET = 59"]
    D --> E["FPGA_SPI_ReadSamples\npkt.samples  n_pairs=59\napb0 bit-bang only — radio safe"]
    E --> F["NSS = LOW\nGPIOA BSRR = NSS_PIN reset bits\nbegin SPI transaction"]
    F --> G["spi_bb_transfer tx=0xA5A5\nFPGA_STREAM_CMD — wake FPGA FIFO"]
    G --> H[i = 0]
    H --> I["spi_bb_transfer tx=0x0000\nreceive ch0 int16"]
    I --> J["spi_bb_transfer tx=0x0000\nreceive ch1 int16"]
    J --> K["pkt.samples[2*i]   = ch0\npkt.samples[2*i+1] = ch1\ni++"]
    K --> L{i == 59?}
    L -->|no| I
    L -->|yes| M["NSS = HIGH\nGPIOA BSRR = NSS_PIN set bits\nend SPI transaction"]
    M --> N["pkt.samples filled\n118 int16 values interleaved\nch0 ch1 ch0 ch1 ..."]
    N --> O[BLE send — see diagram 3]

    subgraph BB ["spi_bb_transfer uint16_t — fully unrolled (GCC -O2 optimization level)"]
        direction TB
        P["entry: tx = word to send\nrx = 0\nSPI_BIT macro expanded\nfor bit 15 down to bit 0\nno loop counter no branch"] --> Q{"tx bit-n\n= 1?"}
        Q -->|yes| R["MOSI = HIGH\nGPIOA BSRR MOSI set\nAPB0 write — never stalls"]
        Q -->|no| S["MOSI = LOW\nGPIOA BSRR MOSI reset\nAPB0 write — never stalls"]
        R --> T["SCK = HIGH\nGPIOB BSRR SCK set"]
        S --> T
        T --> U{"MISO sample\nGPIOA IDR bit 8\nPA8 input"}
        U -->|1| V["rx bit-n = 1"]
        U -->|0| W["rx bit-n = 0"]
        V --> X["SCK = LOW\nGPIOB BSRR SCK reset\n~2 MHz at 64 MHz SYSCLK\n~2.5 us per transfer"]
        W --> X
        X --> Y{"n = 0?\n15 iters done?"}
        Y -->|no  n--| Q
        Y -->|yes| Z["return rx uint16\n~2.5 us elapsed"]
    end

    G -.->|3 calls\n0xA5A5 cmd| P
    I -.->|59 calls\nch0 reads| P
    J -.->|59 calls\nch1 reads| P
```

---

## Diagram 3 — BLE Send & TX Flow Control

```mermaid
flowchart TD
    A["pkt ready — StreamDataPacket_t\ntimestamp_s  timestamp_sub_s\nseq_num  num_pairs=59\npkt.samples[118] filled"] --> B["STREAM_NotifyData\npkt pointer  conn_handle\ncalled from StreamSendTask tight loop"]
    B --> C["aci_gatt_srv_notify\nconn = conn_handle\ncid = BLE_GATT_UNENHANCED_ATT_L2CAP_CID\nhandle = StreamNotifyCharHdle+1\ntype = GATT_NOTIFICATION\nvalue_length = 244 bytes"]
    C --> D{"tBleStatus\nreturn value?"}
    D -->|"0x00 BLE_STATUS_SUCCESS"| E["s_notify_total++\ns_notifs_in_batch++\npacket in LL TX queue"]
    D -->|"0x88 INSUFFICIENT\nRESOURCES"| F["s_txFlowOff = 1\ns_flowoff_total++\nmblock pool exhausted"]
    E --> G["BLE_STACK_Tick\nadvances BLE state machine\nprocesses controller events\nruns LL scheduling"]
    G --> H{"s_txFlowOff\n== 0?"}
    H -->|0 pool free| I["loop back immediately\nbuild next header\nread next 59 pairs"]
    H -->|1 pool full| J[break out of tight loop\nStreamSendTask returns]
    I --> A
    F --> J

    J --> K["UTIL_SEQ_Run returns to idle\nMX_APPE_Process loop\nBLE_STACK_Tick runs in idle\nwaiting for HW event"]
    K --> L{"ACI_GATT_TX_POOL\nAVAILABLE_VSEVT_CODE\nevent fires?"}
    L -->|waiting| K
    L -->|yes — pool drained| M["app_ble.c event handler\nSTREAM_APP_ResumeSending\ns_txFlowOff = 0\ns_resume_total++"]
    M --> N["UTIL_SEQ_SetTask\nCFG_TASK_STREAM_SEND_ID\nbit5 PRIO_1\nreschedule send task"]
    N --> O[StreamSendTask re-enters\ntight loop restarts from top]
    O --> A

    subgraph Radio ["BLE Radio — 32 MHz HSE RF, independent of SYSCLK"]
        P["LL assembles connection event\nDLE payload 251 bytes\n2M PHY bitrate ~2 Mbps\nCI = 7.5 ms nominal"] --> Q["RADIO_TXRX_IRQHandler fires\nNVIC priority 0 — highest\ngates APB1 during radio window\nAPB0 GPIO unaffected"]
        Q --> R["packet transmitted over air\nto WB09KE BLE central\nor Android app directly"]
        R --> S["ACK received in same CI\nnext CI: more packets\nor connection supervision"]
    end

    E -.->|enqueues PDU| P
    G -.->|drives| Q
```
