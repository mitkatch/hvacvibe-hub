hvacvibe-hub/gateway/
├── main.py                  ← orchestrator, starts all threads
├── config.py                ← all settings in one place
├── data_store.py            ← shared state, N sensors, thread-safe
├── ble_scanner.py           ← bleak async, writes to data_store
├── display.py               ← pygame LCD, reads data_store directly
├── cloud_sync.py            ← polls data_store, calls publisher
└── publisher/
    ├── __init__.py          ← factory: get_publisher(config)
    ├── base.py              ← abstract BasePublisher
    ├── http_publisher.py    ← HTTP POST implementation
    └── mqtt_publisher.py    ← stub, same interface, swap later