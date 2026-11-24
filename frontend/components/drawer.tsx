"use client";

import type { ComponentPropsWithoutRef } from "react";
import { useEffect, useId, useRef } from "react";

import { IconButton, X } from "./icons";

export function Drawer({ title, description, onClose, children }: {
  title: string;
  description: string;
  onClose: () => void;
  children: React.ReactNode;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const id = useId();

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    dialog.showModal();
    return () => dialog.close();
  }, []);

  return (
    <dialog ref={ref} className="drawer" aria-labelledby={`${id}-title`} aria-describedby={`${id}-description`}
      onCancel={(event) => { event.preventDefault(); onClose(); }}
      onClick={(event) => { if (event.target === event.currentTarget) onClose(); }}>
      <div className="drawer-content">
        <header className="drawer-header">
          <div><p className="section-label">VEKTOR WORKSPACE</p><h2 id={`${id}-title`}>{title}</h2><p id={`${id}-description`}>{description}</p></div>
          <IconButton label={`Close ${title}`} onClick={onClose}><X size={21} aria-hidden="true" /></IconButton>
        </header>
        <div className="drawer-body">{children}</div>
      </div>
    </dialog>
  );
}

export function ConfirmDialog({ title, description, confirmLabel, onConfirm, onClose, busy = false }: {
  title: string;
  description: string;
  confirmLabel: string;
  onConfirm: () => void;
  onClose: () => void;
  busy?: boolean;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const id = useId();

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    dialog.showModal();
    return () => dialog.close();
  }, []);

  return (
    <dialog ref={ref} className="confirm-dialog" aria-labelledby={`${id}-title`}
      onCancel={(event) => { event.preventDefault(); if (!busy) onClose(); }}>
      <h2 id={`${id}-title`}>{title}</h2><p>{description}</p>
      <div className="dialog-actions">
        <button className="button secondary" onClick={onClose} disabled={busy}>Keep it</button>
        <button className="button danger" onClick={onConfirm} disabled={busy}>{busy ? "Deleting..." : confirmLabel}</button>
      </div>
    </dialog>
  );
}
