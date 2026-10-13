import { removeServer, replaceServer, replaceLink } from "../topology";
import { useCallback, useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ReactFlow,
  Background,
  BackgroundVariant,
  Controls,
  MiniMap,
  useNodesState,
  useEdgesState,
  useReactFlow,
  type Connection,
  type Edge,
  MarkerType,
} from "@xyflow/react";
import { useTranslation } from "react-i18next";
import {
  Plus,
  Search,
  ArrowDownToLine,
  ArrowUpFromLine,
  ArrowLeftRight,
  Waypoints,
  Network,
  GitBranch,
  Layers3,
  LayoutGrid,
  Link2,
  Trash2,
  RotateCcw,
  FileSearch,
} from "lucide-react";
import { api, useTopology, useSaveTopology } from "../api";
import { newId, type Server, type Link, type Topology } from "../types";
import { ServerNode, type ServerFlowNode } from "./ServerNode";
import { ServerDialog } from "./ServerDialog";
import { LinkPanel } from "./LinkPanel";
import { Jobs } from "./Jobs";
import { Modal, Confirm, Spinner, ErrorMessage } from "./Primitives";
const nodeTypes = { server: ServerNode };
const blankLink = (entry: string, exit: string): Link => ({
  id: newId(),
  entry_id: entry,
  exit_id: exit,
  method: "rathole",
  enabled: true,
  ports: [{ public: 443, target: 443, host: "127.0.0.1" }],
  policy: "roundrobin",
  weight: 1,
});
export function Workspace({
  demo,
  onVault,
}: {
  demo: boolean;
  onVault: () => void;
}) {
  const { t } = useTranslation();
  const cache = useQueryClient();
  const query = useTopology();
  const save = useSaveTopology();
  const flow = useReactFlow<ServerFlowNode>();
  const [nodes, setNodes, onNodesChange] = useNodesState<ServerFlowNode>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);
  const [search, setSearch] = useState("");
  const [serverDialog, setServerDialog] = useState<Server | "new" | null>(null);
  const [draft, setDraft] = useState<Link | null>(null);
  const [batch, setBatch] = useState<Connection[]>([]);
  const [confirm, setConfirm] = useState<{
    title: string;
    message: string;
    action: () => void;
  } | null>(null);
  const [notice, setNotice] = useState("");
  const [planOpen, setPlanOpen] = useState(false);
  const topology = query.data;
  const plan = useQuery({
    queryKey: ["preview", topology?.revision],
    queryFn: () =>
      api<
        {
          server_id: string;
          units: string[];
          files: string[];
          ports: number[];
          udp_ports: number[];
        }[]
      >("/preview"),
    enabled: planOpen,
  });
  const action = useMutation({
    mutationFn: (path: string) =>
      api(path, "POST", { revision: topology?.revision }),
    onSuccess: () => {
      void cache.invalidateQueries({ queryKey: ["topology"] });
      void cache.invalidateQueries({ queryKey: ["jobs"] });
      setConfirm(null);
    },
  });
  const positions = useMutation({
    mutationFn: (positions: Record<string, { x: number; y: number }>) =>
      api("/positions", "PATCH", { positions }),
    onSuccess: () => void cache.invalidateQueries({ queryKey: ["topology"] }),
  });
  useEffect(() => {
    if (!topology) return;
    setNodes((old) =>
      topology.servers.map((server) => ({
        id: server.id,
        type: "server",
        position: server.position,
        selected: old.find((n) => n.id === server.id)?.selected,
        data: {
          server,
          status:
            topology.revision === topology.applied_revision
              ? "succeeded"
              : "queued",
          edit: () => setServerDialog(server),
        },
      })),
    );
    setEdges(
      topology.links.map((l) => ({
        id: l.id,
        source: l.entry_id,
        target: l.exit_id,
        label: l.method.replaceAll("_", " ").toUpperCase(),
        type: "smoothstep",
        animated: l.enabled,
        style: {
          stroke: l.enabled
            ? l.method === "gre"
              ? "#a78bfa"
              : "#5cbfa4"
            : "#60716c",
          strokeWidth: 1.5,
          opacity: l.enabled ? 1 : 0.45,
        },
        labelStyle: { fill: "var(--muted)", fontSize: 10, fontWeight: 600 },
        labelBgStyle: { fill: "var(--canvas)" },
        labelBgPadding: [8, 5],
        labelBgBorderRadius: 5,
        markerEnd: { type: MarkerType.ArrowClosed, color: "#5cbfa4" },
      })),
    );
  }, [topology, setNodes, setEdges]);
  useEffect(() => {
    if (!notice) return;
    const timer = setTimeout(() => setNotice(""), 4000);
    return () => clearTimeout(timer);
  }, [notice]);
  function commit(next: Topology) {
    save.mutate(next, {
      onSuccess: () => {
        setServerDialog(null);
        setDraft(null);
        setBatch([]);
        setConfirm(null);
        setNotice(t("queuedNotice"));
      },
    });
  }
  const connect = useCallback((connection: Connection) => {
    if (
      connection.source &&
      connection.target &&
      connection.source !== connection.target
    ) {
      setBatch([]);
      setDraft(blankLink(connection.source, connection.target));
    }
  }, []);
  function saveLink(link: Link) {
    if (!topology) return;
    if (!batch.length) {
      commit(replaceLink(topology, link));
      return;
    }
    const links = batch.length
      ? batch.map((pair) => ({
          ...link,
          id: newId(),
          entry_id: pair.source!,
          exit_id: pair.target!,
        }))
      : [link];
    commit({
      ...topology,
      links: [...topology.links.filter((l) => l.id !== link.id), ...links],
    });
  }
  function saveServer(server: Server) {
    if (!topology) return;
    const next = topology.servers.some((item) => item.id === server.id)
      ? server
      : {
          ...server,
          position: {
            x: server.role === "exit" ? 540 : 80,
            y:
              70 +
              topology.servers.filter((item) => item.role === server.role)
                .length *
                200,
          },
        };
    commit(replaceServer(topology, next));
  }

  function arrange() {
    if (!topology) return;
    const counters = { entry: 0, both: 0, exit: 0 };
    const updated = topology.servers.map((s) => ({
      ...s,
      position: {
        x: { entry: 60, both: 380, exit: 700 }[s.role],
        y: 60 + counters[s.role]++ * 210,
      },
    }));
    setNodes((old) =>
      old.map((n) => ({
        ...n,
        position: updated.find((s) => s.id === n.id)!.position,
      })),
    );
    positions.mutate(
      Object.fromEntries(updated.map((s) => [s.id, s.position])),
    );
    setTimeout(() => void flow.fitView({ padding: 0.15, duration: 500 }), 100);
  }
  function connectSelection() {
    const selected = nodes.filter((n) => n.selected).map((n) => n.data.server);
    const pairs = selected
      .filter((s) => s.role !== "exit")
      .flatMap((a) =>
        selected
          .filter((s) => s.role !== "entry" && s.id !== a.id)
          .map((b) => ({
            source: a.id,
            target: b.id,
            sourceHandle: null,
            targetHandle: null,
          })),
      );
    if (!pairs.length) {
      setNotice(t("connectBatchHint"));
      return;
    }
    setBatch(pairs);
    setDraft(blankLink(pairs[0].source, pairs[0].target));
  }
  if (query.isPending)
    return (
      <div className="loading-screen">
        <Spinner />
        {t("loading")}
      </div>
    );
  if (!topology)
    return (
      <div className="page-content">
        <ErrorMessage error={query.error} />
        <button className="button" onClick={() => void query.refetch()}>
          {t("refresh")}
        </button>
      </div>
    );
  return (
    <div className="workspace">
      <section className="workspace-heading">
        <div>
          <span className="eyebrow">{t("workspace")} / 01</span>
          <h1>{t("networkTitle")}</h1>
          <p>{t("networkSubtitle")}</p>
        </div>
        <button
          className="button primary"
          onClick={() => setServerDialog("new")}
        >
          <Plus size={18} />
          {t("addServer")}
        </button>
      </section>
      <section className="metrics">
        <div>
          <span className="metric-icon">
            <Network size={18} />
          </span>
          <span>
            <small>{t("servers")}</small>
            <strong>{String(topology.servers.length).padStart(2, "0")}</strong>
          </span>
          <span className="metric-detail">
            {topology.servers.filter((s) => s.role === "entry").length}{" "}
            {t("entry")} /{" "}
            {topology.servers.filter((s) => s.role === "exit").length}{" "}
            {t("exit")}
          </span>
        </div>
        <div>
          <span className="metric-icon violet">
            <GitBranch size={18} />
          </span>
          <span>
            <small>{t("connections")}</small>
            <strong>
              {String(topology.links.filter((l) => l.enabled).length).padStart(
                2,
                "0",
              )}
            </strong>
          </span>
          <span className="mini-bars">
            <i />
            <i />
            <i />
            <i />
            <i />
            <i />
            <i />
          </span>
        </div>
        <div title={t("notMonitored")}>
          <span className="metric-icon amber">
            <Layers3 size={18} />
          </span>
          <span>
            <small>{t("applied")}</small>
            <strong className="revision-number">
              r{topology.applied_revision}
            </strong>
          </span>
          <span
            className={
              "sync-pill " +
              (topology.revision === topology.applied_revision ? "synced" : "")
            }
          >
            {t(
              topology.revision === topology.applied_revision
                ? "upToDate"
                : "pending",
            )}
          </span>
        </div>
      </section>
      <div className="workspace-tools">
        <span className="canvas-title">
          <span className="status-dot succeeded" />
          {t("topology")}
          <span className="pill">
            {t("desired")} r{topology.revision}
          </span>
        </span>
        <div>
          <button
            className="icon-button"
            aria-label={t("preview")}
            title={t("preview")}
            onClick={() => setPlanOpen(true)}
          >
            <FileSearch size={17} />
          </button>
          <button
            className="icon-button"
            aria-label={t("autoLayout")}
            title={t("autoLayout")}
            onClick={arrange}
          >
            <LayoutGrid size={17} />
          </button>
          <button
            className="icon-button"
            aria-label={t("connectSelected")}
            title={t("connectSelected")}
            onClick={connectSelection}
          >
            <Link2 size={17} />
          </button>
          <button
            className="icon-button"
            aria-label={t("reconcile")}
            title={t("reconcile")}
            disabled={action.isPending}
            onClick={() => action.mutate("/reconcile")}
          >
            <RotateCcw size={16} />
          </button>
          <button
            className="icon-button danger-text"
            aria-label={t("cleanup")}
            title={t("cleanup")}
            onClick={() =>
              setConfirm({
                title: t("cleanup"),
                message: t("cleanupHint"),
                action: () => action.mutate("/cleanup"),
              })
            }
          >
            <Trash2 size={16} />
          </button>
        </div>
      </div>
      <ErrorMessage
        error={
          (!serverDialog && !draft ? save.error : null) ||
          positions.error ||
          action.error
        }
      />
      <div className="network-stage">
        <aside className="inventory">
          <header>
            <span>{t("inventory")}</span>
            <span>{topology.servers.length}</span>
          </header>
          <div className="search">
            <Search size={15} />
            <input
              aria-label={t("searchServers")}
              placeholder={t("searchServers")}
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </div>
          {(["entry", "both", "exit"] as const).map((role) => {
            const matches = topology.servers.filter(
              (s) =>
                s.role === role &&
                (s.name + " " + s.address)
                  .toLowerCase()
                  .includes(search.toLowerCase()),
            );
            const Icon =
              role === "entry"
                ? ArrowDownToLine
                : role === "exit"
                  ? ArrowUpFromLine
                  : ArrowLeftRight;
            return matches.length ? (
              <div className="inventory-group" key={role}>
                <span className="inventory-label">
                  {t(role)}
                  <small>{matches.length}</small>
                </span>
                {matches.map((s) => (
                  <button
                    key={s.id}
                    draggable
                    onDragStart={(e) =>
                      e.dataTransfer.setData("application/tunnel-server", s.id)
                    }
                    onClick={() => {
                      setNodes((old) =>
                        old.map((n) => ({ ...n, selected: n.id === s.id })),
                      );
                      void flow.setCenter(
                        s.position.x + 120,
                        s.position.y + 85,
                        { zoom: 1, duration: 400 },
                      );
                    }}
                    onDoubleClick={() => setServerDialog(s)}
                  >
                    <span className={"library-icon " + role}>
                      <Icon size={15} />
                    </span>
                    <span>
                      <strong>{s.name}</strong>
                      <small>{s.region || s.address}</small>
                    </span>
                    <span className="drag-dots">⠿</span>
                  </button>
                ))}
              </div>
            ) : null;
          })}
          <button
            className="library-add"
            onClick={() => setServerDialog("new")}
          >
            <Plus size={15} />
            {t("addServer")}
          </button>
          <p className="inventory-tip">{t("selectionHint")}</p>
        </aside>
        <div
          className="canvas-wrap"
          dir="ltr"
          onDragOver={(e) => {
            e.preventDefault();
            e.dataTransfer.dropEffect = "move";
          }}
          onDrop={(e) => {
            e.preventDefault();
            const id = e.dataTransfer.getData("application/tunnel-server");
            if (!topology.servers.some((s) => s.id === id)) return;
            const position = flow.screenToFlowPosition({
              x: e.clientX,
              y: e.clientY,
            });
            setNodes((old) =>
              old.map((n) => (n.id === id ? { ...n, position } : n)),
            );
            positions.mutate({ [id]: position });
          }}
        >
          <ReactFlow
            ariaLabelConfig={{
              "controls.zoomIn.ariaLabel": t("zoomIn"),
              "controls.zoomOut.ariaLabel": t("zoomOut"),
              "controls.fitView.ariaLabel": t("fitView"),
            }}
            nodes={nodes}
            edges={edges}
            nodeTypes={nodeTypes}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            onConnect={connect}
            onReconnect={(edge, connection) => {
              const old = topology.links.find((l) => l.id === edge.id);
              if (old) {
                setBatch([]);
                setDraft({
                  ...old,
                  entry_id: connection.source,
                  exit_id: connection.target,
                });
              }
            }}
            isValidConnection={(c) => {
              const a = topology.servers.find((s) => s.id === c.source),
                b = topology.servers.find((s) => s.id === c.target);
              return (
                !!a &&
                !!b &&
                a.id !== b.id &&
                a.role !== "exit" &&
                b.role !== "entry"
              );
            }}
            onNodeDoubleClick={(_, node) => setServerDialog(node.data.server)}
            onNodeDragStop={(_, node) =>
              positions.mutate({ [node.id]: node.position })
            }
            onEdgeClick={(_, edge) => {
              setBatch([]);
              setDraft(topology.links.find((l) => l.id === edge.id) || null);
            }}
            onPaneClick={() => setDraft(null)}
            deleteKeyCode={null}
            fitView
            fitViewOptions={{ padding: 0.2, maxZoom: 1 }}
            minZoom={0.2}
            maxZoom={1.5}
          >
            <Background variant={BackgroundVariant.Dots} gap={24} size={1} />
            <Controls showInteractive={false} />
            <MiniMap
              nodeColor={(n) =>
                (n.data?.server as Server)?.role === "exit"
                  ? "#a78bfa"
                  : "#5cbfa4"
              }
              maskColor="var(--minimap-mask)"
              pannable
              zoomable
            />
          </ReactFlow>
          {!topology.servers.length && (
            <div className="empty-canvas">
              <div className="empty-icon">
                <Waypoints size={42} />
              </div>
              <h2>{t("emptyTitle")}</h2>
              <p>{t("emptyHint")}</p>
              <button
                className="button primary"
                onClick={() => setServerDialog("new")}
              >
                <Plus size={16} />
                {t("addServer")}
              </button>
              {demo && (
                <button
                  className="text-button"
                  onClick={() => action.mutate("/demo/seed")}
                >
                  {t("loadDemo")}
                </button>
              )}
            </div>
          )}
          <div className="canvas-hint">{t("dragHint")}</div>
        </div>
        {draft && (
          <LinkPanel
            key={draft.id + draft.entry_id + draft.exit_id}
            link={draft}
            servers={topology.servers}
            onSave={saveLink}
            onClose={() => {
              setDraft(null);
              setBatch([]);
            }}
            pending={save.isPending}
            error={save.error}
            count={batch.length || 1}
            onDelete={
              topology.links.some((l) => l.id === draft.id)
                ? () =>
                    setConfirm({
                      title: t("removeConnection"),
                      message: t("removeConnectionHint"),
                      action: () =>
                        commit({
                          ...topology,
                          links: topology.links.filter(
                            (l) => l.id !== draft.id,
                          ),
                        }),
                    })
                : undefined
            }
          />
        )}
      </div>
      <Jobs servers={topology.servers} />
      {serverDialog && (
        <>
          <ServerDialog
            key={typeof serverDialog === "string" ? "new" : serverDialog.id}
            server={serverDialog === "new" ? undefined : serverDialog}
            onSave={saveServer}
            onClose={() => setServerDialog(null)}
            pending={save.isPending}
            error={save.error}
            onVault={() => {
              setServerDialog(null);
              onVault();
            }}
            onDelete={
              serverDialog === "new"
                ? undefined
                : () => {
                    const server = serverDialog;
                    setServerDialog(null);
                    setConfirm({
                      title: t("deleteServer"),
                      message: t("deleteServerHint"),
                      action: () => commit(removeServer(topology, server.id)),
                    });
                  }
            }
          />
        </>
      )}
      {confirm && (
        <Confirm
          {...confirm}
          onConfirm={confirm.action}
          onClose={() => setConfirm(null)}
          pending={save.isPending || action.isPending}
        />
      )}{" "}
      {notice && (
        <div className="toast" role="status">
          {notice}
        </div>
      )}
      {planOpen && (
        <Modal wide title={t("preview")} onClose={() => setPlanOpen(false)}>
          <p className="muted small">{t("planHint")}</p>
          <ErrorMessage error={plan.error} />
          <div className="plan-list">
            {plan.data?.map((p) => (
              <article key={p.server_id}>
                <h3>
                  {topology.servers.find((s) => s.id === p.server_id)?.name}
                </h3>
                <strong>{t("units")}</strong>
                <pre>{p.units.join("\n") || "—"}</pre>
                <strong>{t("files")}</strong>
                <pre>{p.files.join("\n") || "—"}</pre>
                <strong>{t("ports")}</strong>
                <code>{p.ports.join(", ") || "—"}</code>
                <strong>{t("udpPorts")}</strong>
                <code>{p.udp_ports?.join(", ") || "—"}</code>
              </article>
            ))}
          </div>
        </Modal>
      )}
    </div>
  );
}
