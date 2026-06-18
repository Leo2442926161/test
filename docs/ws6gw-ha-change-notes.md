# WS6GW Gateway and Home Assistant Change Notes

这份笔记记录 WS6GW 网关固件和 `heiman_wifi` Home Assistant
集成之间的对接方式，以及最近几轮针对网关页面、水浸子设备和事件更新的修改。

## 总体原则

Home Assistant 侧不要猜每一种 Zigbee 子设备应该有哪些功能点。更稳定的做法是：

1. WS6GW 固件在 `GET /info` 里声明每个子设备支持哪些属性。
2. WS6GW 固件在 `GET /state` 里只上报这些属性的当前值。
3. WS6GW 固件在 `/ws` 的 `device_update` 事件里带同样结构的 `ha_state`。
4. HA 集成按 `/info` 建实体，按 `/state` 和 `/ws ha_state` 更新实体状态。

这样不同设备型号的差异由网关固件控制，HA 集成只负责通用映射。

## 关键文件

HA 集成：

| 文件 | 作用 |
|---|---|
| `custom_components/heiman_wifi/api.py` | HTTP 和 WebSocket 客户端 |
| `custom_components/heiman_wifi/coordinator.py` | 轮询 `/state`/`/info`，订阅 `/ws` 事件 |
| `custom_components/heiman_wifi/model.py` | 把 `/info` 和 `/state` 转成 HA endpoint/property |
| `custom_components/heiman_wifi/sensor.py` | 温度、RSSI、IP/MAC 等 sensor |
| `custom_components/heiman_wifi/binary_sensor.py` | 水浸、门磁、烟感、气感等 binary sensor |
| `custom_components/heiman_wifi/switch.py` | 普通 switch 和网关 `Permit Join` |
| `custom_components/heiman_wifi/button.py` | identify 等按钮 |

WS6GW 固件：

| 文件 | 作用 |
|---|---|
| `/home/leo/leo/esp/proj/study/WS6GW/main/user/local_web_server.c` | `/info`、`/state`、`/control`、`/ws` 和 HA 属性映射 |
| `/home/leo/leo/esp/proj/study/WS6GW/main/web/gateway_dashboard.html` | 网关本地 Web 页面 |

## 子设备功能点怎么增删

以水浸设备为例，核心逻辑都在 WS6GW 的
`main/user/local_web_server.c`。

### 1. 先分类设备类型

设备类型 helper 决定某个 `devType` 属于哪类 Zone 设备：

```c
static bool local_web_is_water_zone_type(uint16_t dev_type)
static bool local_web_is_smoke_zone_type(uint16_t dev_type)
static bool local_web_is_gas_zone_type(uint16_t dev_type)
static bool local_web_is_co_zone_type(uint16_t dev_type)
```

如果新增一个水浸型号，把它的 `NODE_INFO_TYPE_...` 放进
`local_web_is_water_zone_type()`，同时确保它仍在
`local_web_is_zone_sensor_type()` 里。

### 2. 决定 HA 要显示哪些属性

这些 helper 是 capability 开关：

```c
static bool local_web_ha_zone_has_tamper(uint16_t dev_type)
static bool local_web_ha_zone_has_fault(uint16_t dev_type)
static bool local_web_ha_zone_has_status(uint16_t dev_type)
static bool local_web_ha_zone_has_preheat(uint16_t dev_type)
static bool local_web_ha_zone_has_muted(uint16_t dev_type)
static bool local_web_ha_zone_has_concentration(uint16_t dev_type)
static bool local_web_ha_zone_has_temperature(uint16_t dev_type)
static bool local_web_ha_zone_has_humidity(uint16_t dev_type)
```

规则：

- `true` 表示 `/info` 会声明这个属性，HA 会创建实体。
- `false` 表示 `/info` 不声明这个属性，HA 不应该创建新实体。
- 对应的 `/state` 输出也必须用同一个 helper 控制。

当前 HS2 水浸策略：

| 属性 | 当前策略 |
|---|---|
| `water` | 保留，binary_sensor，device_class 为 `moisture` |
| `temperature` | 保留，sensor，单位 `°C` |
| `humidity` | 去掉 |
| `rssi` | 保留，Diagnostic sensor |
| `battery` / `battery_alarm` | 保留 |
| `tamper` | 去掉 |
| `fault` | 去掉 |
| `preheat` | 去掉 |
| `muted` | 去掉 |
| `concentration` | 去掉 |
| `zone_status` | 去掉 |
| `online` / `dev_type` / `endpoint_count` / `short_addr` | 水浸页面去掉，避免普通用户页面太杂 |

### 3. 在 `/info` 声明属性

`local_web_ha_add_type_property_descriptors()` 负责给 `/info` 增加
子设备属性描述。

示例：只给支持温度的 Zone 设备声明温度：

```c
if (local_web_ha_zone_has_temperature(device->devType)) {
    local_web_ha_add_property(
        properties,
        "temperature",
        "Temperature",
        "sensor",
        "temperature",
        "°C",
        "measurement",
        false,
        false);
}
```

如果要删除湿度，确认这里不会为水浸调用：

```c
static bool local_web_ha_zone_has_humidity(uint16_t dev_type)
{
    (void)dev_type;
    return false;
}
```

### 4. 在 `/state` 上报属性

`local_web_ha_add_type_state()` 负责给 `/state` 增加 live value。

示例：只在温度有有效值时上报：

```c
if (local_web_ha_zone_has_temperature(device->devType) && zone->tempMeterage != 0) {
    cJSON_AddNumberToObject(
        properties,
        "temperature",
        local_web_temperature_from_raw(zone->tempMeterage));
}
```

删除湿度时，`local_web_ha_zone_has_humidity()` 返回 `false` 后，这段不会输出：

```c
if (local_web_ha_zone_has_humidity(device->devType) && zone->humiMeterage != 0) {
    cJSON_AddNumberToObject(
        properties,
        "humidity",
        local_web_humidity_from_raw(zone->humiMeterage));
}
```

### 5. WebSocket 事件也要带 HA 状态

`local_web_build_device_update_json()` 会发送：

```json
{
  "type": "device_update",
  "device": { "...": "dashboard shape" },
  "ha_state": {
    "id": "child_ieee",
    "online": true,
    "properties": {
      "water": true,
      "temperature": 25.0,
      "rssi": -60
    }
  }
}
```

HA coordinator 优先使用 `ha_state` 直接更新实体，不需要等 HTTP
轮询。这是水浸报警和恢复能快速显示的关键。

## 温度显示 Unknown 的原因和处理

现象：HA 历史曲线有温度值，但当前状态显示 `Unknown`。

常见原因：

1. 历史记录来自之前某次有效 `/state`。
2. 后续某个 `/ws device_update` 事件没有带 `temperature`。
3. HA 如果用新事件整包替换旧 properties，当前温度就变成 `None`，
   前端显示 `Unknown`。

当前处理方式：

- `coordinator.py` 中的 `EVENT_PRESERVE_PROPERTIES` 包含 `temperature`。
- 收到 `device_update.ha_state.properties` 时，如果事件没带
  `temperature`，但旧状态里有 `temperature`，HA 会保留旧温度。
- 不保留 `humidity`，所以去掉湿度后不会被事件缓存回来。

如果以后还有类似慢变化值，例如 `battery`、`rssi`，可以谨慎加到：

```python
EVENT_PRESERVE_PROPERTIES = {
    "temperature",
}
```

不要把报警类字段加进去，例如 `water`、`open`、`smoke`、`gas`。
这些字段必须完全跟随最新事件，否则报警/恢复会显示错误。

## 水浸报警位

日志示例：

```text
cpAlarm: 0x21
cpAlarm: 0x20
```

对 HS2 水浸：

- `0x21`：bit0 为 1，表示漏水，HA `water = true`。
- `0x20`：bit0 为 0，表示恢复干燥，HA `water = false`。

因此水浸 wet/dry 只看 bit0 和 `zone->alarms`，不能把 bit5 当作漏水。
固件函数：

```c
static bool local_web_ha_zone_alarm_active(
    const HM_DEV_RAM_LIST *device,
    const ZONE_STA_APP *zone)
```

当前对水浸的判断：

```c
if (local_web_is_water_zone_type(device->devType)) {
    return zone->alarms != 0 || (zone->zoneStatus & 0x0001) != 0;
}
```

## 验证步骤

刷固件并重载 HA 集成后，按下面顺序查。

### 1. 检查 `/info`

```bash
curl --noproxy '*' http://<gateway-ip>/info
```

HS2 水浸子设备的 `properties` 应该包含：

```json
{"id": "water", "platform": "binary_sensor", "device_class": "moisture"}
{"id": "temperature", "platform": "sensor", "device_class": "temperature", "unit": "°C"}
{"id": "rssi", "platform": "sensor", "device_class": "signal_strength", "unit": "dBm"}
{"id": "battery", "platform": "sensor", "device_class": "battery", "unit": "%"}
```

不应该包含：

```text
humidity
concentration
fault
tamper
preheat
muted
zone_status
dev_type
endpoint_count
short_addr
```

### 2. 检查 `/state`

```bash
curl --noproxy '*' http://<gateway-ip>/state
```

HS2 水浸子设备的 `properties` 应该有类似：

```json
{
  "water": false,
  "temperature": 25.0,
  "rssi": -60,
  "battery": 100,
  "battery_alarm": false
}
```

如果 `temperature` 不出现，说明固件当前 `zone->tempMeterage` 为 `0`，
网关没有有效温度值。HA 只能保留上一笔有效温度，不能凭空生成当前值。

### 3. 检查 `/ws`

Web 页面本身已经使用 `/ws`。如果要用命令行观察，可以用支持
WebSocket 的工具连接：

```bash
websocat ws://<gateway-ip>/ws
```

连接后发送：

```json
{"type":"get_snapshot"}
```

水浸报警/恢复时应收到 `device_update`，并带 `ha_state`。

### 4. 清理 HA 旧实体

HA 已经创建过的旧实体不会因为 `/info` 删除属性就一定自动消失。
如果以前创建过 `Humidity`、`Zone Status` 等实体：

1. 先重载 `Heiman WiFi` 集成。
2. 如果旧实体还在，到 HA 设备页面手动删除旧实体。
3. 必要时删除该子设备或整个网关配置项，再重新发现。

## 最近修改笔记

### 网关根设备

- `Permit Join` 从按钮改成 switch。
- `Permit Join` 固件侧同时下发 Zigbee permit join 和 RF/subG join。
- 增加 IP Address 和 MAC Address Diagnostic sensors。
- `Zigbee Join Detected` 从 binary sensor 改成 Diagnostic sensor，
  显示 `detected` / `clear`。
- `schema` 不再生成 HA 实体。
- 增加网关 root `identify` action。
- 删除 root `refresh/fresh` 按钮。
- 设备数量名称从 `Zigbee Device Count` 改成 `Device Count`。

### 子设备

- 删除子设备 `refresh/fresh` 按钮。
- 保留子设备 `identify` 按钮。
- 子设备 `identify` 的 `/control` 设备匹配支持 IEEE、反序 IEEE、
  `legacyDeviceId`、设备显示名、index、shortAddr，避免 HA 报
  `device_not_found`。
- 水浸 wet/dry 使用 bit0 判断，修复 `0x21` 报警、`0x20` 恢复。
- HS2 水浸保留 `water`、`temperature`、`rssi`、`battery`、
  `battery_alarm`、`identify`。
- HS2 水浸去掉 `humidity`、`concentration`、`fault`、`tamper`、
  `preheat`、`muted`、`zone_status`、`online`、`dev_type`、
  `endpoint_count`、`short_addr`。
- RSSI 对水浸仍保留，因为硬件支持并且对诊断有价值。
- 震动传感器 `NODE_INFO_TYPE_VIBRATION` 加入 zone sensor 类型：
  HA 子设备会显示 `Alarm` 和 `Tamper`。
- 门磁类型统一走 door zone helper：
  `MAGNET_DOOR`、`HS1_MAGNET_DOOR`、`HS8_MAGNET_DOOR`、`D1_EF2`
  都会显示门磁开合实体和 `Tamper`。
- 门磁和震动的 `Tamper` 以 IAS `zoneStatus` bit2 `0x0004` 为准；
  不再把 `tamperalarms` action code 当作布尔值，避免恢复事件后 HA
  一直显示 `Tampering detected`。
- HA 侧增加 `vibration_sensor` 类型提示，兼容没有完整属性描述但上报了
  二进制状态的震动设备。
- `online` 不再作为子设备实体显示；HA 实体直接根据子设备 state 顶层
  `online` 字段进入 `Unavailable`。
- `Endpoint Count`、`Zone Status`、`Heiman Device Type` 不再生成 HA
  实体。
- HA 不显示子设备删除按钮；`delete` / `delete_device` / `refresh` /
  `permit_join` 都在 HA button 平台过滤。
- 网关收到子设备 leave 或网关侧删除完成时，会通过 `/ws` 发送
  `device_removed`；HA 收到后用 `index/shortAddr` 匹配旧 endpoint，
  将该子设备状态标记为 `online=false`，实体进入 HA 原生
  `Unavailable`。

### HA 实时更新

- `api.py` 增加 `async_ws_connect()`，连接 `ws://<gateway>/ws`。
- `coordinator.py` 增加后台 WebSocket 事件循环。
- 收到 `device_update.ha_state` 时直接更新 coordinator data。
- `temperature` 在事件没带时保留上一笔有效值，避免当前状态变成
  `Unknown`。
- 报警类字段不保留旧值，必须跟随最新事件。

### HA 离线启动与重连

- HA 启动时如果网关还没有上电，集成不会因为第一次 `/state` 或
  `/info` 失败而停止加载。
- coordinator 会先使用配置项里的 host、model、type、mac 生成一个
  fallback root device，让平台注册监听器。
- 离线期间每 10 秒主动请求一次刷新；网关恢复后，成功轮询 `/state`
  和 `/info` 会自动补齐实体，不需要手动重新加载集成。
- WebSocket 事件连接仍然每 5 秒重试一次；连上后会请求 snapshot。
- zeroconf 重新发现网关并更新 config entry 的 host/port 时，运行中的
  HTTP/WebSocket 连接会切到新地址，并立即刷新一次。

### 已知边界

- HA 仍保留 30 秒 HTTP 轮询作为兜底。
- 如果网关断开 `/ws`，HA 会 5 秒后重连。
- 如果固件没有在 `/ws device_update` 中带 `ha_state`，HA 会退回
  HTTP refresh。
- subG 目前只确认 permit join 命令下发；工程里没有独立 subG
  设备表实现，子设备显示仍依赖 `gw_info.pnode_list`。

## 构建和检查命令

HA 语法检查：

```bash
python3 -m py_compile \
  custom_components/heiman_wifi/api.py \
  custom_components/heiman_wifi/coordinator.py \
  custom_components/heiman_wifi/__init__.py \
  custom_components/heiman_wifi/model.py \
  custom_components/heiman_wifi/sensor.py \
  custom_components/heiman_wifi/binary_sensor.py \
  custom_components/heiman_wifi/button.py \
  custom_components/heiman_wifi/switch.py
```

HA diff 检查：

```bash
git diff --check -- custom_components/heiman_wifi
```

WS6GW 固件构建：

```bash
cd /home/leo/leo/esp/proj/study/WS6GW
cmake --build build
```

生成固件：

```text
/home/leo/leo/esp/proj/study/WS6GW/build/WS6GW.bin
```
