import { memo } from "react";
import { Handle, Position, type NodeProps, type Node } from "@xyflow/react";
import {
  ArrowDownToLine,
  ArrowUpFromLine,
  ArrowLeftRight,
  MoreHorizontal,
  PanelLeftClose,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import type { Server } from "../types";
export type ServerFlowNode = Node<
  {
    server: Server;
    status: string;
    edit: () => void;
    readOnly?: boolean;
    hide?: () => void;
    boardLocked?: boolean;
    boardBusy?: boolean;
  },
  "server"
>;
export const ServerNode = memo(function ServerNode({
  data,
  selected,
}: NodeProps<ServerFlowNode>) {
  const { t } = useTranslation();
  const { server, status } = data;
  const Icon =
    server.role === "entry"
      ? ArrowDownToLine
      : server.role === "exit"
        ? ArrowUpFromLine
        : ArrowLeftRight;
  return (
    <div
      className={"server-node " + server.role + (selected ? " selected" : "")}
    >
      <Handle
        id="tunnel-in"
        type="target"
        position={Position.Left}
        isConnectable={!data.readOnly && server.role !== "entry"}
        className={server.role === "entry" ? "hidden-handle" : ""}
      />
      <Handle
        id="jump-in"
        type="target"
        position={Position.Top}
        isConnectable={false}
        className="jump-handle"
      />
      <Handle
        id="jump-out"
        type="source"
        position={Position.Bottom}
        isConnectable={false}
        className="jump-handle"
      />
      <Handle
        id="jump-out-top"
        type="source"
        position={Position.Top}
        isConnectable={false}
        className="jump-handle"
      />
      <Handle
        id="jump-in-bottom"
        type="target"
        position={Position.Bottom}
        isConnectable={false}
        className="jump-handle"
      />
      <div className="node-header">
        <div className="node-icon">
          <Icon size={20} />
        </div>
        <span className="node-role">{t(server.role)}</span>
        {!data.readOnly && (
          <button
            className="nodrag icon-button board-hide"
            onClick={data.hide}
            disabled={data.boardLocked || data.boardBusy}
            aria-label={t("board.hide")}
            title={t(data.boardLocked ? "board.locked" : "board.hideHint")}
          >
            <PanelLeftClose size={16} />
          </button>
        )}
        <button
          className="nodrag icon-button"
          onClick={data.edit}
          aria-label={t(data.readOnly ? "removal.title" : "editServer")}
        >
          <MoreHorizontal size={18} />
        </button>
      </div>
      <strong>{server.name}</strong>
      <div className="node-address mono">{server.address}</div>
      <div className="node-footer">
        <span>
          <i className={"status-dot " + status} />
          {server.region || t(server.role)}
        </span>
        <span className="node-protocol">IPv4</span>
      </div>
      <Handle
        id="tunnel-out"
        type="source"
        position={Position.Right}
        isConnectable={!data.readOnly && server.role !== "exit"}
        className={server.role === "exit" ? "hidden-handle" : ""}
      />
    </div>
  );
});
