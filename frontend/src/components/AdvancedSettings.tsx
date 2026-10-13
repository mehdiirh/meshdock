import { RotateCcw, SlidersHorizontal } from "lucide-react";
import { useTranslation } from "react-i18next";
import type { MethodInfo, MethodSettings } from "../types";
import {
  effectiveSettings,
  settingActive,
  settingsValid,
  updateSetting,
} from "../methodSettings";
import { Field } from "./Primitives";

export function AdvancedSettings({
  method,
  settings,
  onChange,
}: {
  method: MethodInfo;
  settings: MethodSettings;
  onChange: (settings: MethodSettings) => void;
}) {
  const { t } = useTranslation();
  const schema = method.settings_schema;
  if (!schema) return null;
  const effective = effectiveSettings(schema, settings);
  const valid = settingsValid(schema, settings);
  return (
    <details className="advanced-settings">
      <summary>
        <SlidersHorizontal size={16} />
        <span>{t("advanced.title")}</span>
        <span className="advanced-count">
          {Object.keys(settings).length || t("advanced.defaults")}
        </span>
      </summary>
      <div className="advanced-content">
        <p className="small muted">{t(`advanced.methods.${method.id}`)}</p>
        <p className="small muted">{t("advanced.deployHint")}</p>
        <button
          type="button"
          className="text-button"
          onClick={() => onChange({})}
          disabled={!Object.keys(settings).length}
        >
          <RotateCcw size={14} />
          {t("advanced.reset")}
        </button>
        {Object.entries(schema.properties)
          .filter(([, field]) => settingActive(field.when, effective))
          .map(([key, field]) => {
            const label = t(`advanced.fields.${key}`);
            return (
              <div className="advanced-option" key={key}>
                <Field label={label}>
                  {field.enum ? (
                    <div
                      className="advanced-choices"
                      role="group"
                      aria-label={label}
                    >
                      {field.enum.map((choice) => (
                        <button
                          key={String(choice)}
                          type="button"
                          aria-pressed={effective[key] === choice}
                          className={effective[key] === choice ? "active" : ""}
                          onClick={() =>
                            onChange(
                              updateSetting(schema, settings, key, choice),
                            )
                          }
                        >
                          {String(choice)}
                        </button>
                      ))}
                    </div>
                  ) : field.type === "boolean" ? (
                    <button
                      type="button"
                      role="switch"
                      aria-label={label}
                      aria-checked={Boolean(effective[key])}
                      className="advanced-toggle"
                      onClick={() =>
                        onChange(
                          updateSetting(schema, settings, key, !effective[key]),
                        )
                      }
                    >
                      <span />
                      {t(effective[key] ? "advanced.on" : "advanced.off")}
                    </button>
                  ) : (
                    <input
                      type="number"
                      dir="ltr"
                      className="mono"
                      aria-label={label}
                      min={field.minimum}
                      max={field.maximum}
                      step={1}
                      required
                      value={String(effective[key])}
                      onChange={(event) =>
                        onChange(
                          updateSetting(
                            schema,
                            settings,
                            key,
                            event.target.value === ""
                              ? ""
                              : Number(event.target.value),
                          ),
                        )
                      }
                    />
                  )}
                  <small className="muted">
                    {t(`advanced.scope.${field.scope}`)} ·{" "}
                    {t("advanced.default", {
                      value:
                        typeof field.default === "boolean"
                          ? t(field.default ? "advanced.on" : "advanced.off")
                          : field.default,
                    })}
                    {field.unit
                      ? ` · ${t(`advanced.units.${field.unit}`)}`
                      : ""}
                  </small>
                  {field.minimum !== undefined && (
                    <small className="muted">
                      {t("advanced.range", {
                        min: field.minimum,
                        max: field.maximum,
                      })}
                    </small>
                  )}
                </Field>
              </div>
            );
          })}
        {!valid && (
          <p className="error" role="alert">
            {t("advanced.invalid")}
          </p>
        )}
      </div>
    </details>
  );
}
