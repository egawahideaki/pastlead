'use client';
import { useEffect, useState, useRef } from 'react';
import { useParams, useRouter } from 'next/navigation';
import styles from './page.module.css';

interface Message {
    id: number;
    sender_type: string;
    sender_name: string;
    date: string;
    body: string;
}


interface AiAnalysis {
    summary: string;
    status: string;
    next_action: string;
    key_person: string;
    sentiment?: string;
    urgency?: string;
}

export default function ThreadDetail() {
    const params = useParams();
    const router = useRouter();
    const [messages, setMessages] = useState<Message[]>([]);
    const [loading, setLoading] = useState(true);

    // AI State
    const [aiAnalysis, setAiAnalysis] = useState<AiAnalysis | null>(null);
    const [aiLoading, setAiLoading] = useState(true);

    // Prevent double fetch in StrictMode
    const fetchedIdRef = useRef<string | null>(null);

    useEffect(() => {
        if (!params.id) return;

        const currentId = Array.isArray(params.id) ? params.id[0] : params.id;

        // Reset state if ID changes
        if (fetchedIdRef.current !== currentId) {
            setMessages([]);
            setAiAnalysis(null);
            setLoading(true);
            setAiLoading(true);
            fetchedIdRef.current = currentId; // Mark as fetching for this ID

            // Fetch Messages
            fetch(`http://localhost:8000/threads/${currentId}/messages`)
                .then(res => res.json())
                .then(data => {
                    setMessages(data);
                    setLoading(false);
                })
                .catch(err => {
                    console.error(err);
                    setLoading(false);
                });

            // Fetch AI Analysis (Async)
            fetch(`http://localhost:8000/threads/${currentId}/summary`)
                .then(res => res.json())
                .then(data => {
                    setAiAnalysis(data);
                    setAiLoading(false);
                })
                .catch(err => {
                    console.error("AI Analysis failed", err);
                    setAiLoading(false);
                });
        }
    }, [params.id]);

    if (loading) {
        return <div className={styles.loading}>Loading conversation...</div>;
    }

    return (
        <main className={styles.main}>
            <header className={styles.header}>
                <button onClick={() => router.back()} className={styles.backBtn}>
                    ← Back
                </button>
                <h1>Thread Detail</h1>
            </header>

            <div className={styles.container}>

                {/* AI Analysis Section */}
                <div className={styles.aiSection}>
                    <div className={styles.aiHeader}>
                        <span className={styles.aiIcon}>✨</span>
                        <span>AI Insight</span>
                    </div>

                    {aiLoading ? (
                        <div className={styles.loadingAi}>
                            <span className={styles.shimmer}>Generating strategic analysis...</span>
                        </div>
                    ) : aiAnalysis ? (
                        <div className={styles.aiGrid}>
                            <div>
                                <div className={styles.summaryText}>
                                    {aiAnalysis.summary}
                                </div>
                            </div>
                            <div className={styles.metaTags}>
                                <div className={styles.tagRow}>
                                    <span className={styles.tagLabel}>Status:</span>
                                    <span className={`${styles.tagValue} ${styles.status}`}>{aiAnalysis.status}</span>
                                </div>
                                <div className={styles.tagRow}>
                                    <span className={styles.tagLabel}>Next:</span>
                                    <span className={`${styles.tagValue} ${styles.action}`}>{aiAnalysis.next_action}</span>
                                </div>
                                <div className={styles.tagRow}>
                                    <span className={styles.tagLabel}>Key Person:</span>
                                    <span className={styles.tagValue}>{aiAnalysis.key_person || "Unknown"}</span>
                                </div>
                                {aiAnalysis.sentiment && (
                                    <div className={styles.tagRow}>
                                        <span className={styles.tagLabel}>Mood:</span>
                                        <span className={styles.tagValue}>{aiAnalysis.sentiment}</span>
                                    </div>
                                )}
                            </div>
                        </div>
                    ) : (
                        <div className={styles.summaryText}>Analysis unavailable.</div>
                    )}
                </div>

                <div className={styles.timeline}>
                    {messages.map((msg) => (
                        <div key={msg.id} className={styles.messageRow}>
                            <div className={styles.avatar}>
                                {msg.sender_name.charAt(0).toUpperCase()}
                            </div>
                            <div className={styles.content}>
                                <div className={styles.meta}>
                                    <span className={styles.sender}>{msg.sender_name}</span>
                                    <span className={styles.date}>{new Date(msg.date).toLocaleString()}</span>
                                </div>
                                <div className={styles.body}>
                                    {msg.body.split('\n').map((line, i) => (
                                        <p key={i}>{line}</p>
                                    ))}
                                </div>
                            </div>
                        </div>
                    ))}
                </div>
            </div>
        </main>
    );
}
