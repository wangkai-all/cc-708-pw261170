# 架构与协议说明

## 1. 分层

```
Svelte 5 UI (frontend/src)
  │  fetch /api/* （开发期由 Vite 代理，生产期由 FastAPI 同源托管）
FastAPI 路由 (routers/console.py)
  │  Pydantic 校验，采集点白名单强制
服务门面 (service.py)
  ├── demo_directory.py  ldap3 MOCK_SYNC 内存 DIT（唯一“目录”）
  ├── ranged.py          range 分段服务 + 接收装配器（传输无关）
  ├── relationships.py   关系分类 + 别名环解析
  ├── dn_utils.py        ldap3 驱动的 DN 语法处理
  └── values.py          二进制安全解码 / LDIF 编码
```

目录访问只有一个出口：`DemoDirectory.connect()` 返回绑定到同一内存 server 的
ldap3 连接。代码里不存在任何可由请求覆盖的 host/port，因此采集设置无法被重定向。

## 2. DN 处理为什么不能按逗号切

RFC 4514 的 DN 中，逗号只有在 RDN 之间才是分隔符；出现在 RDN *值* 里时必须转义：

- 反斜杠转义：`Doe\, John`
- 十六进制转义：`R \2B D`（`+`）
- 多值 RDN 用 `+` 连接多个 AVA：`cn=alice+uid=alice99`

`dn_utils.parse` 直接调用 ldap3 的 `parse_dn` 状态机，得到
`(属性类型, 原始转义值, 分隔符)` 序列，再按分隔符（`,` 结束一个 RDN，`+` 继续
同一 RDN）重组为 `ParsedDN`。比较规则：

- 属性类型与值都做**大小写无关**比较（RFC 4512/4517，DN 是规范化的大小写无关名）；
- 多值 RDN 实现为 AVA 的 `frozenset`，AVA 顺序不影响相等性；
- 原始拼写完整保留用于展示，规范化只发生在比较键上。

`is_descendant_or_self` 比较 RDN 链的后缀而不是做字符串后缀匹配——
`cn=dc=demo,dc=local,ou=trick,dc=other,dc=com` 不会被误判进 `dc=demo,dc=local`。

## 3. Range 分段（服务约定，非通用保证）

### 3.1 约定

AD 风格的 range 检索用属性选项 `attr;range=low-high` 分页：

| 请求 | 响应 tag | 含义 |
| --- | --- | --- |
| `member`（普通请求，值数超阈值） | `member;range=0-*` | 第 1 段，`*` 表示还有后续 |
| `member;range=3-*` | `member;range=3-*` | 中间段，上界仍开放 |
| `member;range=6-*` | `member;range=9-9` | 末段，**具体上界**表示结束 |

关键规则：**开放段（high=`*`）只承诺“还有数据”，不承诺索引上界**，下一段的起点
是 `low + count`（实际交付值之后），而不是去解析 `*`。

ldap3 的 mock 本身不实现 range（带 range 标记的请求会被当成未知属性返回空），
所以分段由 `DemoRangeService` 在服务层模拟；这是演示目录的约定。接收端
`RangeAssembler` 是传输无关的，它的首轮请求是普通属性名——若服务不支持 range，
响应 tag 不含 `range=`，装配器按单段完整属性处理，天然兼容不支持该约定的服务。

### 3.2 接收端的故障诊断

每收到一段，`_consume_segment` 校验：

- **gap（缺失）**：新段 `low > 上一期望 low`，报告缺失索引区间；
- **overlap（重叠）**：新段 `low < 上一期望 low`；
- **stall（边界不推进）**：收到开放且为空的段，没有可推进的边界——立即终止，
  不会进入热循环（另有 `MAX_ITERATIONS` 兜底）；
- **invalid-tag**：响应 tag 无法解析。

任何故障都会让 `complete=false`，已收到的值仍保留展示，属性明确标记 partial。
搜索表单的 fault injection 只污染第 2 段（第 1 段保持完好以便对照），且作用域
仅限单次装配，不触碰 DIT。

## 4. 三类关系与别名环

| kind | 来源 | 处理 |
| --- | --- | --- |
| `alias` | 对象类含 `alias`，`aliasedObjectName` 指向另一条目 | 可按需展开（解引用） |
| `referral` | 对象类 `referral` 或带 `ref` 属性，值为 ldap(s) URL | 标 external，仅展示 |
| `external-ref` | 普通 DN 属性（seeAlso 等）指向命名上下文外 | 标 external，仅展示 |
| `member` | member/manager/owner 等 DN 属性指向根内条目 | 存在性校验，present/unresolved |

`AliasResolver` 沿 `aliasedObjectName` 行走，visited 集合以解析后小写 DN 为键
（DN 大小写无关）。再次遇到已访问 DN 即判定 `cycle`，返回 `cycle_path` 并**停止
展开**；环上的所有条目原样保留在 DIT 与搜索结果中。指向根外的目标在跨根检查处
停止并标 external，没有任何自动跟随。

## 5. 二进制安全

所有值以 `raw_attributes` 的字节为准：

1. 属性名（去掉 `;option` 后小写）命中已知二进制语法清单 → 直接 base64，不尝试解码；
2. 其他值走**严格 UTF-8**；失败即回退 base64，并附带 `utf8_error` 说明失败字节位置；
3. LDIF 导出对非严格 UTF-8、控制字符、起始空格/冒号/`<` 等情况使用 RFC 2849 的
   `attr:: <base64>` 形式，长行按 76 列折叠。

前端不持有任何“把字节强转文本”的路径；二进制值给原始字节下载链接
（`/api/attributes/binary`）。

## 6. 采集安全边界

- `config.ALLOWED_SEARCH_BASES` 是唯一的搜索根来源，UI 只渲染这份清单；
- `_validate_base` 硬边界：base 必须在命名上下文内，否则 403；
- sub/one 范围只允许从配置采集点发起；base 范围允许根内任意单条目；
- size_limit 有上限（默认 200）；过滤器值经 `escape_filter_chars` 转义；
- 跨根 DN 不报错、不跟随，统一以 external 关系呈现。

## 7. ldap3 mock 的已知怪癖与对应处理

| 怪癖 | 处理 |
| --- | --- |
| 不支持 range 检索 | 服务层 `DemoRangeService` 实现约定，接收端兼容无 range 服务 |
| `size_limit>0` 超限即返回空（all-or-nothing） | 服务层按硬上限取全量后自行切片，`total_matches` 单独计数 |
| one-level 搜索会包含 base 自身 | 保留 mock 行为，测试按实际行为断言 |
| 手写双重转义的 DN 会被 `safe_dn` 再次转义，add 报成功但键损坏 | DN 一律经 `escape_rdn` 构造；bootstrap 后逐条 BASE 检索校验可取回性 |
