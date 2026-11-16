// 사진 첨부 (최대 3장, 5MB): 고르는 즉시 서버에 올려 token 을 받고, 문의를 보낼 때 token 만 함께 보냄
import { useState } from "react";

import { customerApi, errorMessage } from "../services/api";
import { Spinner } from "./ui";

export interface PickedPhoto {
  token: string;
  name: string;
  preview: string;
}

const MAX = 3;
const MAX_BYTES = 5 * 1024 * 1024;

export default function PhotoPicker({ value, onChange, disabled }: { value: PickedPhoto[]; onChange: (v: PickedPhoto[]) => void; disabled?: boolean }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function pick(files: FileList | null) {
    if (!files?.length) return;
    setError("");
    const room = MAX - value.length;
    const list = Array.from(files).slice(0, room);
    if (files.length > room) setError(`사진은 ${MAX}장까지 올릴 수 있습니다.`);
    setBusy(true);
    const added: PickedPhoto[] = [];
    for (const f of list) {
      if (f.size > MAX_BYTES) { setError("사진은 한 장에 5MB까지 올릴 수 있습니다."); continue; }
      try {
        const r = await customerApi.upload(f);
        added.push({ token: r.token, name: r.filename, preview: URL.createObjectURL(f) });
      } catch (err) {
        setError(errorMessage(err));
      }
    }
    setBusy(false);
    onChange([...value, ...added]);
  }

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        {value.map((p) => (
          <div key={p.token} className="relative h-20 w-20 overflow-hidden rounded-lg border border-slate-200 bg-slate-50">
            <img src={p.preview} alt={p.name} className="h-full w-full object-cover" />
            <button type="button" disabled={disabled} aria-label={`${p.name} 빼기`}
              onClick={() => onChange(value.filter((x) => x.token !== p.token))}
              className="absolute right-1 top-1 h-5 w-5 rounded-full bg-black/60 text-xs leading-5 text-white">×</button>
          </div>
        ))}
        {value.length < MAX && (
          <label className="flex h-20 w-20 cursor-pointer flex-col items-center justify-center rounded-lg border border-dashed border-slate-300 bg-white text-xs text-slate-500 hover:border-indigo-400">
            {busy ? <Spinner /> : <><span className="text-lg leading-none">+</span>사진 ({value.length}/{MAX})</>}
            <input type="file" accept="image/jpeg,image/png,image/webp" multiple className="hidden" disabled={disabled || busy}
              onChange={(e) => { pick(e.target.files); e.target.value = ""; }} />
          </label>
        )}
      </div>
      {error && <p className="text-xs text-rose-600">{error}</p>}
    </div>
  );
}
