import { Handle, Position, type Node, type NodeProps } from "@xyflow/react";
import { Network } from "lucide-react";
import { useTranslation } from "react-i18next";

export type JumpFlowNode = Node<{ host: string; port: number }, "jump">;

export function JumpNode({ data }: NodeProps<JumpFlowNode>) {
  const { t } = useTranslation();
  return (
    <div className="jump-node">
      <Network size={18} />
      <span>{t("board.externalJump")}</span>
      <strong className="mono">
        {data.host}:{data.port}
      </strong>
      <small>{t("board.managementOnly")}</small>
      <Handle
        id="jump-out"
        type="source"
        position={Position.Top}
        isConnectable={false}
      />
    </div>
  );
}
