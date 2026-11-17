# ZSoftly changes to Suite Cloud

This is ZSoftly Technologies Inc.'s modified version of [frappe/suite_cloud](https://github.com/frappe/suite_cloud), distributed under the same license, the GNU Affero General Public License v3.0 (see `license.txt`). Every change is offered upstream; this list says what differs from the upstream commit it is based on.

Based on upstream `develop` at `ea8b601` (2026-11-16).

## 2026-11-17: Stalwart 1.x and externally managed clusters

- **Stalwart 1.x schema.** The objects Suite Cloud writes now use the Stalwart 1.0 to 1.1 names:
  - `Domain.enable` (was `isEnabled`), `EmailAlias.enable` (was `enabled`)
  - `Bootstrap.defaultHostname` (was `serverHostname`), `NetworkListener.implicitTls` (was `tlsImplicit`)
  - `MtaRouteRelay.host` (was `address`), `MetricsOtelHttp.url` (was `endpoint`)
  - `MtaMilter.host`, `connectTimeout`, `commandTimeout`, `dataTimeout`
  - the store fields `connectTimeout` (PostgreSQL, Redis) and `idleTimeout` (MySQL), `S3Store.accessKeyId`, the S3 custom region's `url` and `region`, `MeilisearchStore.maxPolls`
  - WebHook event lists without the events Stalwart 1.x removed

  Every plan and payload was checked against the Stalwart v1.1.1 schema (`resources/schema/schema_oss.json.gz`) and against a running v1.1.1 server. New clusters default to Stalwart v1.1.1, stalwart-cli v2.0.0 and spam filter rules v3.0.4.
- **Externally managed clusters.** A new `Externally Managed` option on Stalwart Cluster is for a Stalwart that runs outside Suite Cloud, for example on Kubernetes deployed by Argo CD.
  - **No provisioning.** Suite Cloud never provisions nodes over SSH for such a cluster.
  - **Adoption.** "Adopt External Server" (`adopt_external_server`) applies the cluster plan and the permanent administrator with the server's recovery administrator. It does not store those credentials. It then mints Suite Cloud's API key and marks the cluster active.
  - **Left to the platform:** nodes, stores, listeners, certificates, DNS resolution, logging, the outbound scanner, the telemetry push and the sending-limit hook. The native sending backstop stays.
  - **Private network.** API calls go to the Base URL whatever host the server's JMAP session names (`ConnectionInfo.pin_api_url`). The new `JMAP Service Hostname` sets the host Stalwart writes into its session URLs, which tenants' sites follow.
