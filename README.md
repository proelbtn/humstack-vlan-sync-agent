# humstack-vlan-sync-agent

## 概要

ICTSC2020で利用するネットワーク設定エージェント。humstackで宣言されたネットワークを監視し、対応するネットワーク設定をスイッチに設定する。

## 使用しているライブラリ

- fastcore
- pyyaml
- requests
- netmiko

## config.yml

vlan-sync-agentはconfig.ymlを設定ファイルとして読み込みます。config.ymlの書式は以下の通りです。

```
importer:
  address: http://hogehoge
exporters:
  - type: Cisco4948
    address: fugafuga
    username: user
    password: password
    secret: secret
```

### importer

humstackのAPIサーバに関する設定です。`address`にはAPIサーバのアドレスを設定します。

### exporters

configを流し込むスイッチに関する設定です。

