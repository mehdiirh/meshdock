import type {
  MethodSettings,
  SettingCondition,
  SettingsSchema,
  SettingValue,
} from "./types";

export function effectiveSettings(
  schema: SettingsSchema,
  settings: MethodSettings,
): MethodSettings {
  return {
    ...Object.fromEntries(
      Object.entries(schema.properties).map(([key, field]) => [
        key,
        field.default,
      ]),
    ),
    ...settings,
  };
}

export function settingActive(
  when: SettingCondition | undefined,
  settings: MethodSettings,
) {
  return Object.entries(when || {}).every(([key, choices]) =>
    choices.includes(settings[key]),
  );
}

export function updateSetting(
  schema: SettingsSchema,
  settings: MethodSettings,
  key: string,
  value: SettingValue,
): MethodSettings {
  const next = { ...settings, [key]: value };
  const effective = effectiveSettings(schema, next);
  return Object.fromEntries(
    Object.entries(next).filter(([name]) =>
      settingActive(schema.properties[name]?.when, effective),
    ),
  );
}

export function settingsValid(
  schema: SettingsSchema | undefined,
  settings: MethodSettings = {},
): boolean {
  if (!schema) return Object.keys(settings).length === 0;
  const effective = effectiveSettings(schema, settings);
  for (const [key, value] of Object.entries(settings)) {
    const field = schema.properties[key];
    if (!field || !settingActive(field.when, effective)) return false;
    if (field.enum && !field.enum.includes(value)) return false;
    if (field.type === "boolean" && typeof value !== "boolean") return false;
    if (field.type === "string" && typeof value !== "string") return false;
    if (
      field.type === "integer" &&
      (typeof value !== "number" ||
        !Number.isInteger(value) ||
        value < (field.minimum ?? -Infinity) ||
        value > (field.maximum ?? Infinity))
    )
      return false;
  }
  return schema.rules.every(
    (rule) =>
      !settingActive(rule.when, effective) ||
      (rule.operator === "lt"
        ? Number(effective[rule.left]) < Number(effective[rule.right])
        : Number(effective[rule.left]) <= Number(effective[rule.right])),
  );
}
