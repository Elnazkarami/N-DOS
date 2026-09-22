import { useRef, useState } from "react";

export function JsonDrop({
  label,
  hint,
  onText,
  loadedName,
  error,
}: {
  label: string;
  hint: string;
  onText: (text: string, name: string) => void;
  loadedName?: string | null;
  error?: string | null;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [over, setOver] = useState(false);

  const read = (file: File) => {
    const reader = new FileReader();
    reader.onload = () => onText(String(reader.result ?? ""), file.name);
    reader.readAsText(file);
  };

  return (
    <div>
      <div
        onDragOver={(e) => {
          e.preventDefault();
          setOver(true);
        }}
        onDragLeave={() => setOver(false)}
        onDrop={(e) => {
          e.preventDefault();
          setOver(false);
          const file = e.dataTransfer.files[0];
          if (file) read(file);
        }}
        onClick={() => inputRef.current?.click()}
        className={`riso-panel cursor-pointer px-5 py-6 text-center transition-colors ${
          over ? "bg-cyan/15" : ""
        }`}
      >
        <p className="riso-label">{label}</p>
        <p className="mt-2 font-mono text-sm">
          {loadedName ? loadedName : "Drop a JSON file here, or click to choose one"}
        </p>
        <p className="mt-2 font-mono text-[11px] text-ink/50">{hint}</p>
        <input
          ref={inputRef}
          type="file"
          accept=".json,application/json"
          className="hidden"
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (file) read(file);
          }}
        />
      </div>
      {error ? (
        <p className="mt-2 rounded-sm border border-magenta bg-magenta/15 px-3 py-2 font-mono text-[12px]">
          {error}
        </p>
      ) : null}
    </div>
  );
}
