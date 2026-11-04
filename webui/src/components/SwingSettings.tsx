export function SwingSettings({ value, onChange }: {
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <details className="swing-settings">
      <summary>波段识别尺度 <span>{value || "—"}% 反向确认</span></summary>
      <p>小幅反复不拆段。收盘价从局部极值反向移动到指定幅度，才确认上一个转折。</p>
      <label>
        转折确认幅度
        <span className="input-unit">
          <input aria-label="转折确认幅度" type="number" min="0.01" max="99.99" step="any"
            value={value} onChange={(event) => onChange(event.target.value)} />
          <span>%</span>
        </span>
      </label>
      <p>幅度越大，忽略的细小波动越多；5% 是计算尺度，可调整，不代表有效性或收益。</p>
    </details>
  );
}
