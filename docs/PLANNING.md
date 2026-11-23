# Planning in a Codeman Web Tab

Planning shows the recorded intent and evidence for one configured project.
Features link to the components and tasks explicitly named in the workspace.
Component rows show repository-relative ownership declarations and parent links.
The board status and evidence rungs use the same rules as the CLI.

## Run locally

Install the optional web extra from a local checkout or wheel. The core CLI
can be installed independently.

```sh
pip install '.[web]'
etat-major serve --workspace workspace --project netlens
```

Open `http://127.0.0.1:8765/` on the machine running the service. Use
`--port` to select another loopback port. The server snapshots the inputs at
startup. After changing a record or replacing an artifact, select **Update Planning**
or **Update Fleet** to reload the same configured local inputs. Both views
share the new snapshot and show its load time. A failed update leaves the
previous snapshot in place and displays a message. Restart the service to change
its configured paths, project, or port. Open the page again if its Update link
was loaded before a service restart.

| Option | Input |
| --- | --- |
| `--components` | Component YAML for the configured project. Defaults to `workspace/components/PROJECT.yaml`. A complete seed file can be viewed as a proposal. A proposal delta that relies on existing parents needs to be resolved in the workspace first. |
| `--graph` | Recorded Floorplan graph JSON. |
| `--trail` | Recorded Trail wiring JSON. |
| `--prs` | Recorded pull-request JSON. |
| `--releases` | Recorded release JSON. |
| `--repo` | Local repository for read-only Git history and release containment. |
| `--meute` | [Recorded Meute snapshot](contracts/meute-recording.md) for the configured project. |
| `--manual-review` | [Manual Anthropic API review descriptor](contracts/manual-review.md) for an existing task. |
| `--execution-links` | [Recorded execution links](contracts/execution-links.md) for matching tasks. |
| `--codeman-origin` | Optional trusted HTTPS origin used to display Codeman session URLs. |

Missing or invalid optional inputs are listed under Sources. Planning shows
details for diagnostics attributed to the selected project and counts for
shared decision and research diagnostics. The shared counts are reported
separately from the project diagnostic limit and omit shared record names
and details. A valid component file can establish that a linked declaration
is present or stale. A missing or invalid file leaves the link unverified. Seed rows marked
`inferred_from_gradle` appear as proposed. Ownership paths show declarations.
The root build's `**` catch-all can own files outside named modules, so full
ownership coverage would not imply module-level precision.

The same view is available as JSON at `/project.json`. Both routes use the
startup configuration. The browser page includes its styles inline and uses
fragment links for task navigation.

To include Meute evidence, start Planning with `--meute path/to/snapshot.yaml`.
Sources shows the capture time. A report with an explicit key matching an
existing task in the project appears under that task's Generated evidence
with its reference, timestamp, and outcome. Reports without a matching task
appear in Sources. A valid snapshot appears as `meute` in `/project.json`.
In Planning, an unlinked report whose key belongs to another project appears
without that key. Meute evidence fills only the Generated rung.

With `--manual-review path/to/review.yaml`, that task's Generated evidence
includes the labeled manual review alongside recorded Meute reports. A valid
descriptor appears under `manual_review` in `/project.json`.

Configured execution links appear under **Recorded handoff context** on the
matching task and in `execution_links` in `/project.json`. Copy a session URL
or job reference to use it outside the sandboxed tab. Each handoff also shows a
copyable return URL such as `http://127.0.0.1:8765/planning#task-netlens-0042`.
Use it from a Codeman terminal link to return to the task. Codeman preserves the
path and fragment but matches saved tabs by protocol and loopback port. If
Planning and Fleet share a port, the task can open in the saved Fleet tab. Give
the views distinct service ports when preserving their separate tab identities
matters.

## Add the tab

1. On the Codeman server machine, start the loopback service.
2. Open the chevron beside **Run**, then select **Web / URL** and **Add dashboard…**.
3. Name the tab **Planning** and enter `http://127.0.0.1:8765/`, or use the
   configured port. Keep **Open sandboxed** enabled and save.

Use Codeman’s **Test** to check loopback reachability from its server. Open the
saved tab to verify that the sandboxed browser can render the page and follow
its task and component links.
[Codeman Web Tabs documentation](https://github.com/Ark0N/Codeman/blob/master/docs/web-tabs.md)

## Add the Fleet tab

Add a second **Web / URL** dashboard named **Fleet** with
`http://127.0.0.1:8765/fleet` or the configured port. Keep **Open sandboxed**
enabled. Fleet reads the same optional `--meute` snapshot as Planning. It
shows the capture time, recorded reports and outcomes, and links to matched
Planning tasks inside the same tab. Those links use the `/planning` alias so
they work when Codeman serves Fleet at the Web Tab root. Use **Update Fleet**
after replacing the snapshot. Meute's native UI is where you operate jobs.

## Local verification

During pilot verification, Chromium rendered the installed wheel from a separate working directory inside
an iframe at a simulated `/webview/recorded/` prefix. The frame had an opaque
origin. At 1440 × 1000 and 375 × 812, the page fit the viewport and the
keyboard and fragment links reached the recorded component, its feature, and
the linked task evidence. The run used a real NetLens Floorplan graph, recorded
Trail wiring, and a component proposal seeded from that workspace.
