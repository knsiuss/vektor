"use client";

import Link from "next/link";
import { useState } from "react";

type Lang = "id" | "en";

const CONTENT: Record<
  Lang,
  {
    intro: string;
    sections: Array<{ title: string; href?: string; cta?: string; steps: string[] }>;
  }
> = {
  id: {
    intro:
      "Panduan cepat mengatur Vektor sebagai platform AI Chatbot Omnichannel, Knowledge Base (RAG), Live Inbox, dan Quality Audit.",
    sections: [
      {
        title: "1. Web Chatbot Widget (Website & Aplikasi)",
        href: "/widgets",
        cta: "Buka Web Widgets",
        steps: [
          "Buka halaman Web Widgets dan buat widget baru (isi nama, pesan sambutan, dan domain allowlist, mis. domainmu.com, *.domainmu.com).",
          "Salin potongan <script> yang muncul lalu tempel sebelum tag </body> di website kamu.",
          "Pengunjung langsung bisa chat tanpa login; PII (email, no. HP, NIK, kartu) otomatis disensor sebelum dikirim ke LLM.",
        ],
      },
      {
        title: "2. Omnichannel Bots (Telegram, WhatsApp, Discord)",
        href: "/channels",
        cta: "Buka Channels",
        steps: [
          "Telegram: Buat bot di @BotFather, tempel Bot Token di /channels, lalu klik Auto-Setup Webhook dengan URL HTTPS publik server kamu.",
          "WhatsApp Cloud API (Resmi): Masukkan Phone Number ID, Permanent Access Token, dan Verify Token dari Meta Developers, lalu tempel Webhook URL.",
          "WhatsApp Scan QR (WAHA / Evolution): Jalankan bridge WAHA, scan QR di bridge, masukkan Bridge URL di /channels, dan arahkan webhook bridge ke Webhook URL Vektor.",
          "Discord: Masukkan Application Public Key dan tempel Webhook URL sebagai Interactions Endpoint URL di Discord Developer Portal.",
        ],
      },
      {
        title: "3. Live Inbox, Human Handover & 1-Klik Simpan ke KB",
        href: "/inbox",
        cta: "Buka Inbox",
        steps: [
          "Semua pesan masuk dari Telegram, WhatsApp, dan Discord tampil real-time di /inbox tanpa perlu refresh.",
          "Klik Assign to Me untuk menugaskan CS, lalu klik Take Over jika ingin menghentikan balasan AI dan membalas manual.",
          "Klik Simpan ke KB pada balasan manual admin agar jawaban tersebut otomatis masuk ke Knowledge Base (closed-loop learning).",
          "Aksi tulis (write actions) dari bot masuk ke panel Action Approvals dan hanya berjalan setelah admin klik Approve lalu Execute.",
        ],
      },
      {
        title: "4. Evals & Knowledge Audit (Jaga Kualitas Jawaban)",
        href: "/evals",
        cta: "Buka Evals & Audit",
        steps: [
          "Tambahkan pertanyaan penting beserta Fakta Wajib dan Klaim Terlarang di Golden Q&A Eval Suite.",
          "Klik Run Eval setiap kali mengubah prompt, model, atau dokumen untuk memastikan skor akurasi tetap tinggi.",
          "Pantau panel Knowledge Freshness & Conflict Audit untuk mendeteksi dokumen kadaluarsa (>90 hari) atau judul yang berpotensi konflik.",
        ],
      },
    ],
  },
  en: {
    intro:
      "Quick-start guide to configure Vektor for Omnichannel AI Chatbots, Knowledge Base (RAG), Live Inbox Handover, and Quality Evals.",
    sections: [
      {
        title: "1. Web Chatbot Widget (Websites & Apps)",
        href: "/widgets",
        cta: "Open Web Widgets",
        steps: [
          "Open Web Widgets and create a widget with a name, welcome message, and allowed domains (e.g. yoursite.com, *.yoursite.com).",
          "Copy the generated <script> snippet and paste it before the closing </body> tag on your site.",
          "Visitors can chat without logging in; sensitive PII (email, phone, ID numbers, cards) is automatically redacted before reaching external LLMs.",
        ],
      },
      {
        title: "2. Omnichannel Bots (Telegram, WhatsApp, Discord)",
        href: "/channels",
        cta: "Open Channels",
        steps: [
          "Telegram: Create a bot via @BotFather, paste the Bot Token in /channels, and click Auto-Setup Webhook with your public HTTPS URL.",
          "WhatsApp Cloud API (Official): Enter Phone Number ID, Permanent Access Token, and Verify Token from Meta Developers, then configure the Webhook URL.",
          "WhatsApp QR Bridge (WAHA / Evolution): Run your WAHA bridge, scan the QR code there, enter the Bridge URL in /channels, and point bridge webhooks to Vektor.",
          "Discord: Enter your Application Public Key and set the Webhook URL as the Interactions Endpoint URL in the Discord Developer Portal.",
        ],
      },
      {
        title: "3. Live Inbox, Human Handover & 1-Click Promote to KB",
        href: "/inbox",
        cta: "Open Inbox",
        steps: [
          "Incoming conversations from Telegram, WhatsApp, and Discord stream live into /inbox via SSE.",
          "Click Assign to Me to claim a thread, and Take Over to pause AI auto-replies and respond manually.",
          "Click Simpan ke KB on any human agent reply to index that Q&A directly into your tenant Knowledge Base.",
          "Write actions drafted by the bot appear in Action Approvals and only run after an admin clicks Approve and Execute.",
        ],
      },
      {
        title: "4. Evals & Knowledge Audit (Quality Assurance)",
        href: "/evals",
        cta: "Open Evals & Audit",
        steps: [
          "Add critical test questions with Expected Facts and Forbidden Claims in the Golden Q&A Eval Suite.",
          "Click Run Eval before publishing prompt, model, or document updates to prevent regressions.",
          "Check Knowledge Freshness & Conflict Audit to spot stale documents (>90 days old) and overlapping policies.",
        ],
      },
    ],
  },
};

export function GuideContent() {
  const [lang, setLang] = useState<Lang>("id");
  const data = CONTENT[lang];

  return (
    <div className="ops-stack">
      <div className="ops-row">
        <p className="ops-metric-label" style={{ margin: 0, maxWidth: 680 }}>
          {data.intro}
        </p>
        <div style={{ display: "flex", gap: 6 }}>
          <button
            type="button"
            onClick={() => setLang("id")}
            className={`ops-tab ${lang === "id" ? "is-active" : ""}`}
          >
            Bahasa Indonesia
          </button>
          <button
            type="button"
            onClick={() => setLang("en")}
            className={`ops-tab ${lang === "en" ? "is-active" : ""}`}
          >
            English
          </button>
        </div>
      </div>

      {data.sections.map((sec) => (
        <section key={sec.title} className="ops-card ops-stack">
          <div className="ops-row">
            <strong style={{ fontSize: 15 }}>{sec.title}</strong>
            {sec.href && sec.cta && (
              <Link href={sec.href} className="ops-back">
                {sec.cta}
              </Link>
            )}
          </div>
          <ol style={{ margin: 0, paddingLeft: 20, display: "flex", flexDirection: "column", gap: 6, fontSize: 13, lineHeight: 1.6 }}>
            {sec.steps.map((step, i) => (
              <li key={i}>{step}</li>
            ))}
          </ol>
        </section>
      ))}
    </div>
  );
}
