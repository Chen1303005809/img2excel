# 临时模板配置接口逆向记录

目标站点：`https://192.168.5.31:48081`

本记录来自前端静态资源分析、已登录页面观察和测试环境实测（2026-09-17）。已实际创建一条持仓限制明细和一条开仓总量限制明细，并通过页面回读验证；没有执行发布/生效操作。

## 1. 通用请求约定

API 前缀：

```text
https://192.168.5.31:48081/admin-api
```

请求头至少需要：

```http
Authorization: Bearer <ACCESS_TOKEN>
Content-Type: application/json
```

如果租户模式启用，还需要带当前浏览器本地存储中的：

```http
tenant-id: <TENANT_ID>
```

页面把 token 存在 `ACCESS_TOKEN`，租户 ID 存在 `TENANT_ID`。未登录请求会返回 HTTP 200、业务码 `401` 和“账号未登录”，所以脚本需要复用浏览器会话中的 token，或实现登录/刷新 token。

## 2. 推荐业务流程

```text
读取旧临时模板
  -> （用户确认后）删除旧模板
  -> 创建新的临时模板，得到 templateId
  -> 写入开仓总量限制明细
  -> 写入持仓限制明细
  -> 分页查询校验
```

删除是不可恢复操作。测试过程中旧持仓临时模板 `test` 曾被删除，随后重新创建为持仓临时模板 ID `180`；开仓总量临时模板 `1234` 的 ID 为 `140`。没有调用发布/生效接口。两套模板的删除接口分别为：

```text
POST /datacloud/temp-open-total-limit/temp-release-record/delete?id=<id>
POST /datacloud/temp-position-limit/temp-release-record/delete?id=<id>
```

## 3. 开仓总量限制模板

### 3.1 临时模板记录

```text
GET  /datacloud/temp-open-total-limit/temp-release-record/list
POST /datacloud/temp-open-total-limit/temp-release-record/page
GET  /datacloud/temp-open-total-limit/temp-release-record/get?id=<id>
POST /datacloud/temp-open-total-limit/temp-release-record/create
POST /datacloud/temp-open-total-limit/temp-release-record/update
POST /datacloud/temp-open-total-limit/temp-release-record/copy?id=<id>
POST /datacloud/temp-open-total-limit/temp-release-record/delete?id=<id>
```

创建临时模板的最小请求体：

```json
{
  "templateName": "自动生成的临时模板",
  "remark": "由结构化数据生成"
}
```

对应请求：

```text
POST /admin-api/datacloud/temp-open-total-limit/temp-release-record/create
```

### 3.2 明细保存

```text
POST /datacloud/temp-open-total-limit/detail/page
GET  /datacloud/temp-open-total-limit/detail/get?id=<detailId>
POST /datacloud/temp-open-total-limit/detail/create
POST /datacloud/temp-open-total-limit/detail/update
POST /datacloud/temp-open-total-limit/detail/batch-delete?ids=<序列化后的数组>
```

配置页按“期货”和“期权”两个页签查询：

```json
{
  "pageNo": 1,
  "pageSize": 10,
  "instrumentid": "",
  "isproduct": [0, 1],
  "isopt": 0,
  "templateid": "<templateId>"
}
```

期权页只把 `isopt` 改成 `1`。

一个明细的请求体形状如下。创建时通常不带 `id`；更新时带已有明细的 `id`：

```json
{
  "templateid": "<templateId>",
  "limitvolume": 10000,
  "limitwarnvolume": 8000,
  "isproduct": 0,
  "onlydepth": 1,
  "producttype": "1",
  "isopt": 0,
  "instrumentidText": "豆粕",
  "instrumentidlist": ["豆粕"]
}
```

实际页面提交时还可能保留表单里的未使用字段；后端 DTO 应以以上业务字段为主。`instrumentidText` 是用逗号拼接 `instrumentidlist` 得到的文本，多个标的例如：

```json
{
  "instrumentidText": "豆粕,玉米",
  "instrumentidlist": ["豆粕", "玉米"]
}
```

页面逻辑确认的规则：

- `limitvolume` 和 `limitwarnvolume` 会被转换为数字。
- 预警值不能大于限额值。
- `isopt: 0` 为期货，`isopt: 1` 为期权。
- `producttype` 在品种/合约选择中使用字符串值 `"1"` 或 `"2"`；选择品种时页面会强制为 `"1"`。
- `onlydepth` 只在期权的部分选择场景使用，取值应沿用页面字典，不建议自行猜测。

### 3.3 开仓总量明细实测请求

在临时模板 `1234`（`templateid=140`）上，选择期货品种 `AF`，选择“单品种日内开仓总量限制”，开仓总量填 `2000`、预警填 `100`，浏览器实际发送：

```http
POST /admin-api/datacloud/temp-open-total-limit/detail/create
Content-Type: application/json
tenant-id: 10000
```

```json
{
  "templateid": "140",
  "limitvolume": "2000",
  "limitwarnvolume": "100",
  "isproduct": 1,
  "onlydepth": 1,
  "producttype": "1",
  "isopt": 0,
  "instrumentidText": "AF",
  "instrumentidlist": ["AF"]
}
```

接口返回 `{"code":0,"data":true,"msg":""}`。随后页面查询得到新增明细：

```json
{
  "templateid": 140,
  "instrumentid": "AF",
  "limitvolume": 2000,
  "limitwarnvolume": 100,
  "isopt": 0,
  "isproduct": 1,
  "onlydepth": 0,
  "id": 22
}
```

这次实测确认了：期货页签对应 `isopt=0`；选择“品种”对应 `isproduct=1`、`producttype="1"`；`instrumentidText` 与 `instrumentidlist` 必须同时传。请求中的 `onlydepth=1` 被服务端回读为 `0`，因此不要把它当作稳定的业务开关，按页面当前默认值发送即可。页面展示的“单品种日内开仓总量限制”与上述 `isproduct=1,isopt=0` 组合一致。

## 4. 持仓限制模板

### 4.1 临时模板记录

接口路径与开仓总量限制相同，只替换业务前缀：

```text
GET  /datacloud/temp-position-limit/temp-release-record/list
POST /datacloud/temp-position-limit/temp-release-record/page
GET  /datacloud/temp-position-limit/temp-release-record/get?id=<id>
POST /datacloud/temp-position-limit/temp-release-record/create
POST /datacloud/temp-position-limit/temp-release-record/update
POST /datacloud/temp-position-limit/temp-release-record/copy?id=<id>
POST /datacloud/temp-position-limit/temp-release-record/delete?id=<id>
GET  /datacloud/temp-position-limit/temp-release-config/get?id=<id>
```

创建请求体仍是：

```json
{
  "templateName": "自动生成的临时持仓限制模板",
  "remark": "由结构化数据生成"
}
```

### 4.2 持仓明细保存

```text
POST /datacloud/temp-position-limit/detail/create
POST /datacloud/temp-position-limit/detail/update
POST /datacloud/temp-position-limit/detail/page
POST /datacloud/temp-position-limit/detail/update-warn-line
```

页面查询明细的请求体：

```json
{
  "pageNo": 1,
  "pageSize": 10,
  "productid": "",
  "instrumentCode": null,
  "templateid": "<templateId>",
  "exchangeCode": null,
  "productClass": null
}
```

保存预警线的请求体：

```json
{
  "releaseId": "<templateId>",
  "active": true,
  "warn": 80
}
```

### 4.3 明细请求体

页面最终提交的是一个包含 `templateDetailBaseVOList` 的对象。示例骨架：

```json
{
  "templateid": "<templateId>",
  "templateDetailBaseVOList": [
    {
      "productid": "豆粕",
      "positiondirection": 2,
      "producttype": 1,
      "hedgeflag": "0",
      "templateDetailListBaseVOList": [
        {
          "start": -1,
          "end": -1,
          "startmonth": -1,
          "startday": -1,
          "startdaytype": 0,
          "startordertype": 0,
          "endmonth": -1,
          "endday": -1,
          "enddaytype": 0,
          "endordertype": 0
        }
      ],
      "positionlimitNumberCreateReqVOList": [
        {
          "templatedetailid": "<前端生成的明细行 ID>",
          "positionlower": 0,
          "positionupper": -1,
          "maxpositiontype": 0,
          "maxposition": 1000,
          "dis": true
        }
      ]
    }
  ]
}
```

页面提交时还会保留一些表单辅助字段，例如 `mainRow`、`insList`、`productClass`、字典列表等。直接复刻页面行为时可以先完整发送页面生成的对象；若后端只接受 DTO 字段，再逐步删减辅助字段并用查询接口回读验证。

页面新增一组明细行时，使用 `Math.ceil(9999999 * Math.random())` 生成一个前端数字 ID，并同时作为该组的 `index`、日期行的 `id` 和限仓行的 `templatedetailid`。因此直接模拟页面时可以用一个不重复的正整数贯穿这三个字段；它不是模板主 ID。

字段规则：

- `producttype`: `1` 为期货，`2` 为期权。
- `positiondirection`: `0` 多仓，`1` 空仓，`2` 所有方向。
- `hedgeflag`: 页面默认是字符串 `"0"`，具体含义由 `DATACLOUD_HEDGE_FLAG` 字典决定。
- `productid`: 页面选择器最终使用的品种/合约标识，不能仅凭显示名称臆造；应从页面选择器或已存在明细中取得。选择器使用的只读接口包括：

  ```text
  GET /admin-api/datacloud/exchange/simple-list
  GET /admin-api/datacloud/instrument/simple-map
  GET /admin-api/datacloud/instrument/getByProductType
  ```

  树形搜索/展开时会传 `key`、`limitLevel`、`parentId`、`productType` 等查询参数，返回对象中的 `id` 才是更可靠的 `productid` 来源；`fullName` 主要用于显示和回填文本。
- `positionupper: -1` 表示页面中的 `+∞`。
- `maxpositiontype: 0` 为固定数量；`1` 为百分比。
- 当 `maxpositiontype` 为 `1` 时，页面显示的百分数会除以 `100` 再提交，例如显示 `25`，请求值为 `0.25`。
- `templatedetailid` 是同一日期区间和限仓梯度之间的关联值。页面新建时用前端生成的临时 ID；如果后端不接受临时 ID，应先用浏览器录制一次真实提交验证其格式。

日期区间字段由页面的可视化选项转换为后端特殊值。已确认的转换如下：

```text
第一段 start=-1  -> startmonth=-1, startday=-1
后续段   start=-1 -> startmonth=-2, startday=-2, startdaytype=0
任意段   start=1  -> startmonth=-3
任意段   end=-1   -> endmonth=-1, endday=-1, enddaytype=0
任意段   end=1    -> endmonth=-3
```

普通日历条件则使用正数月份、日期，并配合：

```text
startdaytype/enddaytype: 0 交易日，1 自然日
startordertype/endordertype: 0 第，1 倒数第
```

### 4.4 持仓明细实测回读

在重新创建的持仓临时模板 `test`（`templateid=180`）上，实际新增了“中国金融期货交易所 / AF / 所有方向 / 所有投保标志 / 合约挂牌至交割月份 / 固定 1000”的明细。页面回读请求为：

```http
POST /admin-api/datacloud/temp-position-limit/detail/page
Content-Type: application/json
tenant-id: 10000
```

```json
{
  "pageNo": 1,
  "pageSize": 10,
  "productid": "",
  "templateid": "180"
}
```

回读结果中的新增记录为：

```json
{
  "key": "1_AF_2_0",
  "exchangeid": "CFFEX",
  "productid": "AF",
  "positiondirection": "2",
  "hedgeflag": 0,
  "producttype": 1,
  "templateid": 180,
  "exchangename": "中国金融期货交易所",
  "tempPositionLimitDetailSimpleRespVOList": [
    {
      "id": 11300,
      "startmonth": -1,
      "startday": -1,
      "startdaytype": "0",
      "endmonth": -1,
      "endday": -1,
      "enddaytype": "0",
      "detailorder": 1,
      "startordertype": 0,
      "endordertype": 0,
      "valueStr": "合约挂牌至交割月份"
    }
  ],
  "tempPositionLimitNumberRespVOList": [
    {
      "id": 11520,
      "templatedetailid": 11300,
      "positionupper": -1,
      "positionlower": 0,
      "maxposition": 1000,
      "maxpositiontype": "0",
      "numberorder": 1
    }
  ]
}
```

这次实测确认了：`中国金融期货交易所 / AF` 映射为 `exchangeid=CFFEX, productid=AF`；“所有方向”映射为 `positiondirection=2`；“所有投保标志”回读为 `hedgeflag=0`；“合约挂牌至交割月份”使用月份/日期 `-1` 哨兵；`+∞` 使用 `positionupper=-1`；固定限仓 1000 使用 `maxpositiontype=0,maxposition=1000`。`11300` 和 `11520` 是服务端落库后生成的明细 ID，不能预先写死。

本次持仓提交时网络面板未开启，因此没有保留 `detail/create` 的原始 wire body；上面的创建骨架、前端静态转换规则和这份成功回读结果共同确定了可直接构造的字段映射。若后续需要逐字节复刻页面发送的辅助字段，再单独录制一次即可，不影响当前业务字段结论。

## 5. 还原请求时的验证方式

建议脚本每次保存后立即查询并比对：

```text
开仓总量：POST /datacloud/temp-open-total-limit/detail/page
持仓限制：POST /datacloud/temp-position-limit/detail/page
```

不要只根据创建接口的返回值判断成功；页面创建/保存后也会再次查询列表或明细。后续自动化脚本应记录：请求 URL、请求体、响应业务码、模板 ID、明细 ID，并在出现业务校验错误时停止后续写入。

## 6. 已确认与剩余业务约定

1. “品种/合约名称”不能盲目把显示名称当成 ID。实测选择器中的 `AF` 直接回读为 `productid=AF`，交易所回读为 `exchangeid=CFFEX`；通用脚本仍应通过选择器接口或本地映射表取得内部标识。
2. 持仓的方向、投保标志、日期哨兵和限仓梯度已经用 AF 样例验证。其他日期语义（如交割月前、最后交易日）和百分比限仓仍应按项目导出字段逐项套用前端转换规则，必要时增加对应测试样例。
3. 两类模板的接口前缀、创建流程和明细保存接口彼此独立。是否一次运行同时生成两类临时模板属于上层业务流程选择，不是接口强制要求；按输入表类型生成对应模板即可。
