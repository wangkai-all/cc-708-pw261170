# 样例文件

全部由运行中的演示目录真实输出生成（非手工编造），对应四类边界情况。

## `escaped-and-multirdn-entries.ldif`

转义 DN 与多值 RDN 条目（RFC 2849 LDIF）：

- `cn=Doe\, John,...` —— 值内逗号转义；注意 `jpegPhoto::` 是二进制 base64 形式，
  导出的字节经 base64 解码后与 DIT 中的原始字节一致；
- `cn=alice+uid=alice99,...` —— 多值 RDN，两个 AVA 共同命名条目；
- `cn=Carol \"C\"\+Cao\, \<retired\>\;,...` —— 单个 RDN 值内含引号、`+`、逗号、
  尖括号、分号等全部需转义字符，解析后仍是一个 RDN。

## `ranged-member-conversation.json`

`cn=all-staff` 的 10 个 member 分 4 段接收（页大小 3）：

```
member            -> member;range=0-*   (3 值)
member;range=3-*  -> member;range=3-*   (3 值)
member;range=6-*  -> member;range=6-*   (3 值)
member;range=9-*  -> member;range=9-9   (1 值，具体上界 = 末段)
```

含每段请求/响应 tag、low/high/count、`expected_next_low` 与覆盖统计，
`missing_indices` 为空且 `complete=true` 时接收端才显示属性完整。

## `alias-loop-resolution.json`

`cn=alias-a → cn=alias-b → cn=alias-a` 的别名环。`status=cycle`、
`cycle_path` 首尾相同；展开在此阻断，两个别名条目都不会被删除。

## `range-fault-stall.json`

故障注入（stall）后的 range 报告：第 2 段为空且上界开放，接收端报告
`stall`、停止拉取，属性 `complete=false`，已收到的第 1 段仍然保留。
同一入口还可注入 `gap`（索引跳跃）与 `overlap`（low 回退）。

## `external-referrals.json`

referral 对象与跨根引用：`ref` 里的 ldap/ldaps URL 和根外 DN 一律
`status=external`，只展示不跟随。
