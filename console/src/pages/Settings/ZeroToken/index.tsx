import { useCallback, useEffect, useState } from "react";
import {
  Card,
  Badge,
  Space,
  Typography,
  message,
  Popconfirm,
  Spin,
} from "antd";
import { Button } from "@agentscope-ai/design";
import {
  ChromeOutlined,
  LoginOutlined,
  ReloadOutlined,
  DeleteOutlined,
  CheckCircleOutlined,
  CloseCircleOutlined,
  ClockCircleOutlined,
} from "@ant-design/icons";
import { useTranslation } from "react-i18next";
import api from "../../../api";
import type { WebProviderInfo } from "../../../api/modules/zeroToken";

const { Title, Text } = Typography;

const STATUS_MAP = {
  active: { color: "green", icon: <CheckCircleOutlined />, label: "Active" },
  expired: {
    color: "orange",
    icon: <ClockCircleOutlined />,
    label: "Expired",
  },
  not_configured: {
    color: "default",
    icon: <CloseCircleOutlined />,
    label: "Not Configured",
  },
} as const;

export default function ZeroTokenPage() {
  const { t } = useTranslation();
  const [providers, setProviders] = useState<WebProviderInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [capturing, setCapturing] = useState<string | null>(null);

  const fetchProviders = useCallback(async () => {
    try {
      setLoading(true);
      const data = await api.listProviders();
      // Filter to only web providers (those from zero-token endpoint)
      // We need to call the zero-token specific endpoint
      const webData = await fetch("/api/zero-token/providers").then((r) =>
        r.json(),
      );
      setProviders(webData);
    } catch {
      message.error("Failed to load web providers");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchProviders();
  }, [fetchProviders]);

  const handleStartChrome = async () => {
    try {
      const res = await api.startChrome();
      if (res.success) {
        message.success(`Chrome started (PID: ${res.pid})`);
      } else {
        message.error(res.message || "Failed to start Chrome");
      }
    } catch {
      message.error("Failed to start Chrome");
    }
  };

  const handleLogin = async (providerId: string) => {
    setCapturing(providerId);
    try {
      const response = await fetch(
        `/api/zero-token/login/${encodeURIComponent(providerId)}`,
        { method: "POST" },
      );
      const reader = response.body?.getReader();
      if (!reader) return;

      const decoder = new TextDecoder();
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        const text = decoder.decode(value, { stream: true });
        const lines = text.split("\n");
        for (const line of lines) {
          if (line.startsWith("data: ")) {
            try {
              const event = JSON.parse(line.slice(6));
              if (event.status === "success") {
                message.success(`${providerId}: Credentials captured!`);
              } else if (event.status === "timeout") {
                message.warning(
                  `${providerId}: Timeout - please log in first`,
                );
              } else if (event.status === "error") {
                message.error(`${providerId}: ${event.message}`);
              }
            } catch {
              // ignore parse errors
            }
          }
        }
      }
    } catch {
      message.error(`Failed to capture credentials for ${providerId}`);
    } finally {
      setCapturing(null);
      fetchProviders();
    }
  };

  const handleDelete = async (providerId: string) => {
    try {
      await api.deleteCredential(providerId);
      message.success("Credential deleted");
      fetchProviders();
    } catch {
      message.error("Failed to delete credential");
    }
  };

  if (loading) {
    return (
      <div style={{ textAlign: "center", padding: 48 }}>
        <Spin size="large" />
      </div>
    );
  }

  return (
    <div style={{ padding: 0 }}>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          marginBottom: 24,
        }}
      >
        <div>
          <Title level={4} style={{ margin: 0 }}>
            Zero-Token
          </Title>
          <Text type="secondary">
            Browser-based credential capture for AI platforms
          </Text>
        </div>
        <Space>
          <Button icon={<ChromeOutlined />} onClick={handleStartChrome}>
            Start Chrome
          </Button>
          <Button icon={<ReloadOutlined />} onClick={fetchProviders}>
            Refresh
          </Button>
        </Space>
      </div>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fill, minmax(320px, 1fr))",
          gap: 16,
        }}
      >
        {providers.map((provider) => {
          const statusInfo =
            STATUS_MAP[provider.status as keyof typeof STATUS_MAP] ||
            STATUS_MAP.not_configured;
          const isCapturing = capturing === provider.id;

          return (
            <Card
              key={provider.id}
              size="small"
              title={
                <Space>
                  <span>{provider.name}</span>
                  <Badge
                    status={
                      statusInfo.color === "green"
                        ? "success"
                        : statusInfo.color === "orange"
                          ? "warning"
                          : "default"
                    }
                    text={statusInfo.label}
                  />
                </Space>
              }
              extra={
                <Space size="small">
                  <Button
                    type="link"
                    size="small"
                    icon={<LoginOutlined />}
                    loading={isCapturing}
                    onClick={() => handleLogin(provider.id)}
                  >
                    {isCapturing ? "Capturing..." : "Login"}
                  </Button>
                  {provider.status !== "not_configured" && (
                    <Popconfirm
                      title="Delete this credential?"
                      onConfirm={() => handleDelete(provider.id)}
                    >
                      <Button
                        type="link"
                        size="small"
                        danger
                        icon={<DeleteOutlined />}
                      />
                    </Popconfirm>
                  )}
                </Space>
              }
            >
              <div style={{ fontSize: 12, color: "#666" }}>
                <div>
                  <Text type="secondary">Login URL: </Text>
                  <a
                    href={provider.login_url}
                    target="_blank"
                    rel="noreferrer"
                  >
                    {provider.login_url}
                  </a>
                </div>
                <div>
                  <Text type="secondary">Models: </Text>
                  {provider.models.map((m) => m.name).join(", ")}
                </div>
                {provider.captured_at && (
                  <div>
                    <Text type="secondary">Captured: </Text>
                    {new Date(provider.captured_at).toLocaleString()}
                  </div>
                )}
              </div>
            </Card>
          );
        })}
      </div>
    </div>
  );
}
