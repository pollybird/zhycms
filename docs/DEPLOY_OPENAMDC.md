# openAMDC 部署指南（ZhyCMS v3.3.0）

openAMDC 是 openEuler 社区的 Redis 兼容内存数据库（源于 Redis 6.2 分支）。
ZhyCMS 通过标准 `REDIS_URL` 使用它，缓存、会话、限流与 JWT 吊销均无需改代码。

## 一、验证状态

| 项目 | 状态 | 说明 |
| --- | --- | --- |
| openAMDC 1.0.0 | 已验证（x86_64 + aarch64/鲲鹏） | 源码 commit `6758505d722a7efa0fd64dec5164e19885942f87`，`INFO server` 返回 `openamdc_version:1.0.0` |
| 协议兼容 | 已验证 | RESP2 / RESP3、Lua、`SET NX EX`、`INCR`、`SCAN`、`FLUSHDB` 正常 |
| 全量测试 | 已验证 | 以 `REDIS_URL` 指向 openAMDC 跑通全量 pytest |
| 并发原子性 | 已验证 | 200 线程 `SET NX` 唯一持有者 1；Lua 限流 200 并发恰好放行 10 |
| Docker 镜像 | 已验证 | `pollybird/openamdc:1.0.0`（x86_64 / aarch64 多架构；GHCR / ACR / Docker Hub） |
| 哨兵 | 可用但需手工 | 镜像不创建 `openamdc-sentinel` 符号链接；本项目不内置哨兵逻辑 |
| 集群模式 | 未验证 | 上游保留 `cluster-enabled`，本次未验证 |
| TLS（`rediss://`） | 未验证 / 当前镜像未启用 | 镜像默认未开启 TLS，需自行重编译并配置证书 |

> aarch64 上 79 项端到端实测（后端识别、缓存、会话、限流、JWT 吊销、Lua、分布式锁、
> Pipeline、事务、Hash/List/ZSet 等）记录见
> [信创适配专题](XINCHUANG_ADAPTATION.md) 第八节。

## 二、构建镜像

社区无官方镜像，仓库提供固定 commit 的构建文件：

```bash
docker build -t pollybird/openamdc:1.0.0 docker/openamdc
```

同时支持 x86_64 与 aarch64 多架构镜像（需 buildx 与 QEMU binfmt）：

```bash
docker buildx build --platform linux/amd64,linux/arm64 \
  -t pollybird/openamdc:1.0.0 --push docker/openamdc
```

可覆盖构建参数：

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| `BASE_IMAGE` | `openeuler/openeuler:24.03-lts-sp1` | 信创基座；网络受限时可换本地镜像源 |
| `OPENAMDC_REPO` | `https://atomgit.com/openeuler/openAMDC.git` | 源码地址 |
| `OPENAMDC_REF` | `6758505d722a7efa0fd64dec5164e19885942f87` | 固定 commit，保证可复现 |
| `MAKE_JOBS` | `nproc` | 编译并发数；QEMU 模拟 ARM 构建时建议设为 4 左右 |

构建说明：

- RocksDB 静态链接，首次构建耗时较长，需预留充足超时与磁盘空间；
- aarch64 在 x86_64 主机上通过 QEMU 模拟编译，耗时明显长于本机构建；
- aarch64 启动需忽略内核 COW 告警，默认配置已内置 `ignore-warnings ARM64-COW-BUG`；
- ARM 源码编译需 `libsnappy`（RocksDB 依赖），镜像已内置，容器部署无需额外处理；
- 运行期只依赖 `libstdc++`、`snappy`、`zlib`，无需编译工具链；
- 容器以 uid 999 非 root 运行；
- 许可证文件随镜像放在 `/usr/share/licenses/openamdc/LICENSE`。

## 三、Docker Compose 用法

`docker-compose.yml` 与 `docker-compose.opengauss.yml` 均内置 `openamdc` 服务，
以 profile 方式与 `redis` 并列，默认不启动：

```bash
# MySQL + openAMDC
docker compose --profile mysql --profile openamdc up -d

# PostgreSQL + openAMDC
docker compose --profile postgres --profile openamdc up -d

# openGauss + openAMDC
docker compose -f docker-compose.opengauss.yml --profile openamdc up -d
```

应用侧只需把 `REDIS_URL` 指向该服务：

```conf
REDIS_URL=redis://openamdc:6379/0
```

安装器（`bash docker/install.sh`）的「缓存与 Session」步骤可直接选择 openAMDC；
镜像缺失时会自动从源码构建。

启动后验证：

```bash
docker compose exec openamdc openamdc-cli ping          # PONG
docker compose exec openamdc openamdc-cli INFO server   # openamdc_version
curl -s 'http://127.0.0.1:5000/healthz?detail=1'        # redis_flavor=openamdc
```

## 四、配置项

镜像基线配置位于 `docker/openamdc/openamdc.conf`：

| 配置 | 默认值 | 说明 |
| --- | --- | --- |
| `bind` | `0.0.0.0` | 容器内监听地址 |
| `protected-mode` | `no` | 容器网络隔离，生产请配合网络策略 |
| `port` | `6379` | 与 Redis 客户端默认端口一致 |
| `worker-threads` | `4` | 多线程命令执行；已实测 Lua 与 `SET NX` 跨线程原子 |
| `save` | `""` | 关闭 RDB 快照，符合纯缓存语义 |
| `appendonly` | `no` | 关闭 AOF |
| `maxmemory` | `256mb` | 内存上限，按实例规格调整 |
| `maxmemory-policy` | `allkeys-lru` | 缓存淘汰策略 |
| `swap-enabled` | `no` | 关闭 RocksDB 冷热分层，避免缓存延迟抖动 |
| `databases` | `16` | 与 Redis 相同的库数量 |

常改项直接通过命令行覆盖，无需重建镜像：

```yaml
command: ["/etc/openamdc/openamdc.conf", "--maxmemory", "512mb", "--maxmemory-policy", "allkeys-lru"]
```

> `worker-threads` 建议不超过 CPU 核数。多线程只影响命令执行并行度，
> 单条命令与 Lua 脚本仍保持原子语义（已实测）。

## 五、与 Redis 的差异

| 维度 | Redis | openAMDC | 影响 |
| --- | --- | --- | --- |
| 可执行文件 | `redis-server` / `redis-cli` / `redis-sentinel` | `openamdc-server` / `openamdc-cli` / `openamdc-benchmark` | 健康检查与运维脚本命令名不同 |
| 版本字段 | `INFO` 的 `redis_version` | `openamdc_version`（无 `redis_version`） | 应用按 `openamdc_version` 识别后端 |
| 运行模式字段 | 无 | `openamdc_mode`、`worker_threads`、`openamdc_git_sha1` | 便于审计与排障 |
| `CLIENT SETINFO` | 7.0+ 支持 | 不支持（返回 `ERR Unknown subcommand`） | redis-py 8.x 自动忽略，不影响连接 |
| 并发模型 | 单线程执行命令 | 多 worker 线程 + `SO_REUSEPORT` | 原子性已实测，未见行为差异 |
| 持久化默认 | RDB + AOF 可配 | 镜像默认全部关闭 | 仅作缓存，重启后会话失效属预期 |
| 冷热分层 | 无 | RocksDB `swap-*` | 默认关闭 |

应用侧识别逻辑：`INFO server` 有 `openamdc_version` 即为 openAMDC，其次才看
`redis_version`；异常或无字段时标记为 `unknown`，不影响启动。

## 六、哨兵

openAMDC 代码支持哨兵（按 `argv[0]` 识别），但 `make install` 与镜像都**不会**
自动创建 `openamdc-sentinel` 符号链接。需要时手工创建：

```bash
ln -s /usr/local/bin/openamdc-server /usr/local/bin/openamdc-sentinel
openamdc-sentinel /etc/openamdc/sentinel.conf --sentinel
```

sentinel 配置示例：

```conf
port 26379
sentinel monitor mymaster openamdc 6379 1
sentinel down-after-milliseconds mymaster 5000
```

> 本项目只接受单个 `REDIS_URL`，不内置哨兵自动切换。若使用哨兵，请在部署侧
> 通过 VIP、代理（如 HAProxy）或自行实现的服务发现提供稳定入口。

## 七、升级与回退

openAMDC 的版本由源码 commit 决定：

1. 查看当前版本：`openamdc-cli INFO server | grep openamdc_`；
2. 修改 `OPENAMDC_REF` 后重新构建镜像，并以新 tag 部署；
3. 回退时把镜像 tag 改回旧版本即可。缓存数据无持久化，回退不涉及数据迁移。

ZhyCMS 无需跟随 openAMDC 升级做任何代码改动；只使用 Redis 6.2 范围内的命令。

## 八、TLS

当前交付镜像未启用 TLS，`rediss://` 连接会失败。如需加密传输：

- 以 `BUILD_TLS=yes` 重新编译 openAMDC，并在 `openamdc.conf` 配置
  `tls-port`、`tls-cert-file`、`tls-key-file`、`tls-ca-cert-file`；
- 或在前置代理（Nginx / HAProxy / stunnel）终结 TLS，应用仍使用 `redis://` 连内网；
- `rediss://` 与证书参数在本次交付中**未验证**，启用前请先在测试环境验证。

## 九、常见问题

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| `[Redis] REDIS_URL=... 但连接失败，回退 SimpleCache` | 容器未启动或地址错误 | 检查 `openamdc` profile 与服务名，`openamdc-cli ping` |
| `healthz` 的 `redis_flavor` 为 `unknown` | `INFO server` 无版本字段或连接异常 | 确认连接的是 openAMDC；查看启动日志 `backend=` |
| `ERR Unknown subcommand` 出现在日志 | redis-py 发送 `CLIENT SETINFO` | 客户端自动忽略，可忽略该日志 |
| 重启后登录态全部失效 | 镜像默认关闭 RDB/AOF | 缓存语义使然；需要持久化时自行开启 `save` / `appendonly` |
| Lua 脚本报错 | 使用了 Redis 7 新命令 | openAMDC 对齐 6.2，避免 7.x 专属命令 |
| 容器内存持续上涨 | `maxmemory` 过大或淘汰策略不匹配 | 调整 `maxmemory`，确认 `allkeys-lru` |
| 镜像构建失败 | 基础镜像或源码拉取失败 | 用 `--build-arg BASE_IMAGE=...` 指定可用镜像源 |
