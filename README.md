# LDAP 接收台（LDAP Reception Console）

一个只读的 LDAP 目录接收台，连接**项目自带的演示目录**（基于 ldap3 内存 mock，
无需任何外部 LDAP 服务）。网页上选定搜索根、范围和字段后取回条目，浏览 DN、
对象类型、多值属性以及条目之间的引用。

后端：Python + ldap3 + FastAPI；前端：Svelte 5 + Vite。

## 需求对照

| 要求 | 实现位置 |
| --- | --- |
| DN 转义、大小写比较、多值 RDN 按库规范解释，**不按逗号切串** | `backend/app/ldap_console/dn_utils.py`（全部走 `ldap3.utils.dn.parse_dn` 状态机） |
| 大属性按带范围标记的多段返回（演示服务约定，不假定所有服务支持） | `backend/app/ldap_console/ranged.py`：`DemoRangeService`（分段）+ `RangeAssembler`（接收），接收端同时兼容不返回 range 标记的服务 |
| 接收端补齐全部段后才显示属性完整 | `RangeAssembler` 装配成功才置 `complete=true`；故障时属性标记 `partial`，前端可见 |
| 别名、引用、普通成员关系分别保存 | `backend/app/ldap_console/relationships.py`，三类 `kind`：`alias` / `referral`(+`external-ref`) / `member` |
| 循环只阻断展开，不删除条目 | `AliasResolver` 带 visited 集合，环返回 `status=cycle` 和 `cycle_path`；条目仍在 DIT 和搜索结果中 |
| 二进制属性不强行 UTF-8 解码 | `backend/app/ldap_console/values.py`：已知二进制语法不尝试解码，其他值严格 UTF-8，失败即转 base64 并记录错误 |
| 采集设置只允许访问演示目录 | `config.ALLOWED_SEARCH_BASES` + `service._validate_base`；跨根 base 返回 403 |
| 跨根引用先展示为外部引用，不自动跟随 | referral 对象和跨根 DN 值统一标 `status=external`，只展示 URL/DN，无任何跟随逻辑 |
| 网页展开多值属性的实际接收段，检查缺失/重叠/边界不推进 | 前端 `RangeInspector.svelte` + 后端故障注入（gap/overlap/stall） |
| 下载包含属性类型的结果 | JSON 导出每属性带 `syntax`（text/binary）；LDIF 按 RFC 2849 带属性名、二进制用 `::` base64 |
| 转义 DN、多值 RDN、分段属性、别名环样例 | `samples/` 目录（由真实服务输出生成） |

## 目录结构

```
backend/
  app/ldap_console/
    config.py           # 只允许演示目录的采集设置、二进制/DN 属性清单、range 参数
    dn_utils.py         # ldap3 驱动的 DN 解析、转义、大小写无关比较、多值 RDN 集合比较
    demo_directory.py   # ldap3 MOCK_SYNC 内存 DIT（含全部边界样例条目）
    ranged.py           # range 分段服务 + 接收装配器 + 故障诊断
    relationships.py    # 别名/引用/成员分类、别名环检测展开
    values.py           # 二进制安全解码、LDIF 编码
    exporters.py        # JSON / LDIF 导出
    service.py          # 门面：搜索守卫、range 装配、条目水合
    routers/console.py  # FastAPI 路由
    main.py             # 应用工厂（含构建后静态托管）
  tests/                # 59 个 pytest 用例
frontend/
  src/
    App.svelte
    lib/api.js
    lib/components/      # SearchForm / EntryList / EntryDetail / AttributeTable
                         # / RangeInspector / RelationshipPanel / DnInspector
samples/                 # 真实输出抓取的样例
docs/architecture.md     # 设计细节与协议说明
```

## 运行

需要 Python 3.11+、Node 20+。

```bash
# 1. 后端依赖（仓库根目录）
python3 -m venv .venv
.venv/bin/pip install -r backend/requirements.txt -r backend/requirements-dev.txt

# 2. 启动后端（http://127.0.0.1:8000）
backend/run.sh

# 3. 前端依赖与开发服务器（http://127.0.0.1:5173，/api 代理到 8000）
cd frontend && npm install --cache /tmp/npm-cache   # 缓存目录权限受限时
npm run dev
```

### 单源模式（构建后只开一个端口）

```bash
cd frontend && npm run build
cd ../backend && ./run.sh        # FastAPI 检测到 frontend/dist 后直接托管
# 打开 http://127.0.0.1:8000/
```

### 测试

```bash
cd backend && ../.venv/bin/python -I -m pytest tests/ -q
```

## 演示目录里有什么

22 个条目，刻意覆盖所有边界情况：

- `cn=Doe\, John,ou=people,...` —— 值里带逗号的**转义 DN**（按逗号切串会损坏）；
  还带二进制 `jpegPhoto`（首字节 `0xFF 0xD8`，非 UTF-8）
- `cn=alice+uid=alice99,ou=people,...` —— **多值 RDN**
- `cn=Carol "C"\+Cao\, <retired>\;...` —— 集齐全部需转义字符的 RDN
- `cn=all-staff,ou=groups,...`（10 个 member）、`cn=router-01,ou=devices,...`
  （11 个 `revisionHistory`、7 个 `auditLog`）—— 超过阈值即**分段返回**
- `cn=alias-a ↔ cn=alias-b`、`cn=alias-self` —— **别名环/自环**；
  `cn=john-alias` 正常别名；`cn=dangling-alias` 悬空别名
- `cn=partner-directory,ou=externals,...` —— referral 对象，ldap/ldaps URL，
  **只展示不跟随**；`cn=erin` 的 `seeAlso` 指向根外 DN
- `cn=dave` 的 `manager` 指向不存在的条目 —— 未解析成员，保留并标记

## 界面操作要点

1. 左侧选搜索根（只列允许的采集点）、范围（base/one/sub）、属性与字段过滤；
2. 结果列表点条目，抽屉里分 **Attributes / Relationships** 两个页签；
3. 分段属性在 “Range retrieval segments” 里可展开每个实际接收段
   （请求/响应 tag、low/high、count、下一 low、缺失索引、故障说明）；
4. 搜索表单底部可注入 gap / overlap / stall 故障，观察接收端如何诊断；
5. 二进制值显示字节数和 base64，可下载原始字节；
6. 别名条目可一键展开，遇环显示阻断路径；外部引用只展示；
7. 顶部 Download JSON / LDIF 下载带属性类型的完整结果。
