// 사진 첨부 (최대 3장, 5MB): 고르는 즉시 서버에 올려 token 을 받고, 문의를 보낼 때 token 만 함께 보냄
import { useState } from "react";

import { customerApi, errorMessage } from "../services/api";
import { Spinner } from "./ui";

export interface PickedPhoto {
  token: string;
  name: string;
  preview: string;
}

const MAX_BYTES = 5 * 1024 * 1024;
const MAX_EDGE = 2000;          // 긴 변을 이 크기로 줄임 (상담원이 파손을 확인하기에 충분)
const SHRINK_OVER = 1.5 * 1024 * 1024;

/** 휴대폰 사진(보통 4~10MB)을 올리기 전에 줄임: 긴 변 2000px, JPEG 85%. 줄이지 못하면(형식 등) 원본 그대로 */
export async function shrinkImage(file: File): Promise<File> {
  if (!file.type.startsWith("image/") || file.size <= SHRINK_OVER) return file;
  try {
    const bitmap = await createImageBitmap(file);
    const scale = Math.min(1, MAX_EDGE / Math.max(bitmap.width, bitmap.height));
    const canvas = document.createElement("canvas");
    canvas.width = Math.round(bitmap.width * scale);
    canvas.height = Math.round(bitmap.height * scale);
    canvas.getContext("2d")!.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
    bitmap.close();
    const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, "image/jpeg", 0.85));
    if (!blob || blob.size >= file.size) return file;
    return new File([blob], file.name.replace(/\.\w+$/, "") + ".jpg", { type: "image/jpeg" });
  } catch {
    return file;
  }
}

export default function PhotoPicker({ value, onChange, disabled, max: MAX = 3 }: {
  value: PickedPhoto[]; onChange: (v: PickedPhoto[]) => void; disabled?: boolean; max?: number;
}) {
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
    for (const original of list) {
      const f = await shrinkImage(original);   // 큰 사진은 줄여서 올림
      if (f.size > MAX_BYTES) { setError("사진이 너무 커요. 한 장에 5MB까지 올릴 수 있어요."); continue; }
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
              className="absolute right-0.5 top-0.5 h-7 w-7 rounded-full bg-black/60 text-sm leading-7 text-white">×</button>
          </div>
        ))}
        {value.length < MAX && MAX > 0 && (
          <label className="flex h-20 w-20 cursor-pointer flex-col items-center justify-center rounded-lg border border-dashed border-slate-300 bg-white text-xs text-slate-500 hover:border-indigo-400 focus-within:ring-2 focus-within:ring-primary/40">
            {busy ? <Spinner /> : <><span className="text-lg leading-none">+</span>사진 ({value.length}/{MAX})</>}
            <input type="file" accept="image/jpeg,image/png,image/webp" multiple className="sr-only" disabled={disabled || busy}
              onChange={(e) => { pick(e.target.files); e.target.value = ""; }} />
          </label>
        )}
      </div>
      {error && <p role="alert" className="text-xs text-rose-600">{error}</p>}
    </div>
  );
}

/** 이름 붙은 사진 한 칸 (파손 문의의 '송장', '파손 부위'): 한 장만, 고르면 바로 올림 */
export function PhotoSlot({ label, guide, value, onChange, disabled, missing }: {
  label: string; guide: string; value: PickedPhoto | null; onChange: (v: PickedPhoto | null) => void; disabled?: boolean; missing?: boolean;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function pick(picked: File | undefined) {
    if (!picked) return;
    setError("");
    const file = await shrinkImage(picked);   // 큰 사진은 줄여서 올림
    if (file.size > MAX_BYTES) { setError("사진이 너무 커요. 한 장에 5MB까지 올릴 수 있어요."); return; }
    setBusy(true);
    try {
      const r = await customerApi.upload(file);
      onChange({ token: r.token, name: r.filename, preview: URL.createObjectURL(file) });
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className={`flex items-center gap-3 rounded-xl border p-2.5 ${missing ? "border-rose-300 bg-rose-50/60" : "border-hairline bg-white"}`}>
      {value ? (
        <div className="relative h-20 w-20 shrink-0 overflow-hidden rounded-lg border border-slate-200 bg-slate-50">
          <img src={value.preview} alt={`${label} 사진`} className="h-full w-full object-cover" />
          <button type="button" disabled={disabled} aria-label={`${label} 사진 빼기`} onClick={() => onChange(null)}
            className="absolute right-0.5 top-0.5 h-7 w-7 rounded-full bg-black/60 text-sm leading-7 text-white">×</button>
        </div>
      ) : (
        <label className="flex h-20 w-20 shrink-0 cursor-pointer flex-col items-center justify-center rounded-lg border border-dashed border-slate-300 bg-white text-xs text-slate-500 hover:border-indigo-400 focus-within:ring-2 focus-within:ring-primary/40">
          {busy ? <Spinner /> : <><span className="text-lg leading-none">+</span>사진</>}
          <input type="file" accept="image/jpeg,image/png,image/webp" className="sr-only" disabled={disabled || busy}
            aria-label={`${label} 사진 올리기`} onChange={(e) => { pick(e.target.files?.[0]); e.target.value = ""; }} />
        </label>
      )}
      <div className="min-w-0 text-sm">
        <p className="font-semibold text-ink">{label} 사진 <span className={value ? "text-emerald-700" : "text-rose-600"}>{value ? "✓" : "(필수)"}</span></p>
        <p className="text-xs text-muted">{guide}</p>
        {error && <p role="alert" className="text-xs text-rose-600">{error}</p>}
      </div>
    </div>
  );
}
