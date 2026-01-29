import React from 'react';
import styles from './SettingsModal.module.css';

interface IgnoreItem {
    id: number;
    value: string;
    type: 'email' | 'domain';
}

interface SettingsModalProps {
    isOpen: boolean;
    onClose: () => void;
}

export default function SettingsModal({ isOpen, onClose }: SettingsModalProps) {
    const [items, setItems] = React.useState<IgnoreItem[]>([]);
    const [newValue, setNewValue] = React.useState('');
    const [newType, setNewType] = React.useState<'email' | 'domain'>('domain');
    const [loading, setLoading] = React.useState(false);

    React.useEffect(() => {
        if (isOpen) {
            fetchItems();
        }
    }, [isOpen]);

    const fetchItems = async () => {
        try {
            const res = await fetch('http://localhost:8000/settings/ignore');
            const data = await res.json();
            setItems(data);
        } catch (e) {
            console.error(e);
        }
    };

    const handleAdd = async () => {
        if (!newValue.trim()) return;
        setLoading(true);
        try {
            const res = await fetch('http://localhost:8000/settings/ignore', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ value: newValue.trim(), type: newType }),
            });
            if (res.ok) {
                setNewValue('');
                fetchItems();
            } else {
                alert('Failed or duplicate');
            }
        } catch (e) {
            console.error(e);
        }
        setLoading(false);
    };

    const handleDelete = async (id: number) => {
        if (!confirm('この項目を削除しますか？')) return;
        try {
            await fetch(`http://localhost:8000/settings/ignore/${id}`, { method: 'DELETE' });
            fetchItems();
        } catch (e) {
            console.error(e);
        }
    };

    const handleDownload = () => {
        if (items.length === 0) return;

        // Group by type
        const domains = items.filter(i => i.type === 'domain').map(i => i.value);
        const emails = items.filter(i => i.type === 'email').map(i => i.value);

        let content = "PastLead Ignored Contacts\n=========================\n\n";

        if (domains.length > 0) {
            content += "[Domains]\n";
            content += domains.join('\n');
            content += "\n\n";
        }

        if (emails.length > 0) {
            content += "[Emails]\n";
            content += emails.join('\n');
            content += "\n";
        }

        const blob = new Blob([content], { type: 'text/plain' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');

        // Format date: YYYYMMDDHHMM
        const now = new Date();
        const yyyy = now.getFullYear();
        const MM = String(now.getMonth() + 1).padStart(2, '0');
        const dd = String(now.getDate()).padStart(2, '0');
        const hh = String(now.getHours()).padStart(2, '0');
        const mm = String(now.getMinutes()).padStart(2, '0');
        const dateStr = `${yyyy}${MM}${dd}${hh}${mm}`;

        a.href = url;
        a.download = `IgnoredContacts_${dateStr}.txt`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
    };

    const handleFileUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
        const file = e.target.files?.[0];
        if (!file) return;

        const reader = new FileReader();
        reader.onload = async (event) => {
            const text = event.target?.result as string;
            if (!text) return;

            await processImport(text);
        };
        reader.readAsText(file);

        // Reset input
        e.target.value = '';
    };

    const processImport = async (text: string) => {
        const lines = text.split('\n');
        let currentSection: 'domain' | 'email' | null = null;
        const importItems: { value: string; type: 'email' | 'domain' }[] = [];

        for (const line of lines) {
            const trimmed = line.trim();
            if (!trimmed || trimmed.startsWith('=') || trimmed.startsWith('PastLead')) continue;

            if (trimmed === '[Domains]') {
                currentSection = 'domain';
                continue;
            }
            if (trimmed === '[Emails]') {
                currentSection = 'email';
                continue;
            }

            if (currentSection) {
                importItems.push({ value: trimmed, type: currentSection });
            }
        }

        if (importItems.length === 0) {
            alert('ファイル内に有効な項目が見つかりませんでした。');
            return;
        }

        setLoading(true);
        try {
            const res = await fetch('http://localhost:8000/settings/ignore/import', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ items: importItems })
            });
            const result = await res.json();
            alert(`インポート完了: ${result.added}件\nスキップ（重複）: ${result.skipped}件`);
            fetchItems();
        } catch (error) {
            console.error(error);
            alert('インポートに失敗しました。');
        }
        setLoading(false);
    };



    if (!isOpen) return null;

    return (
        <div className={styles.overlay} onClick={onClose}>
            <div className={styles.modal} onClick={e => e.stopPropagation()}>
                <div className={styles.header}>
                    <h2>設定: 非表示リスト</h2>
                    <button className={styles.closeBtn} onClick={onClose}>×</button>
                </div>

                <div className={styles.content}>
                    <p className={styles.description}>
                        連絡先リストから非表示にするドメインやメールアドレスを追加してください。
                        (例: "company.com" や "bob@example.com")
                    </p>

                    <div style={{ marginBottom: '1.5rem', textAlign: 'right', display: 'flex', gap: '10px', justifyContent: 'flex-end' }}>
                        <label className={styles.uploadBtn}>
                            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                                <polyline points="17 8 12 3 7 8" />
                                <line x1="12" y1="3" x2="12" y2="15" />
                            </svg>
                            インポート
                            <input type="file" accept=".txt" onChange={handleFileUpload} style={{ display: 'none' }} />
                        </label>
                        <button onClick={handleDownload} className={styles.downloadBtn}>
                            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                                <polyline points="7 10 12 15 17 10" />
                                <line x1="12" y1="15" x2="12" y2="3" />
                            </svg>
                            リストをダウンロード
                        </button>
                    </div>


                    <div className={styles.addForm}>
                        <select
                            value={newType}
                            onChange={e => setNewType(e.target.value as any)}
                            className={styles.select}
                        >
                            <option value="domain">ドメイン</option>
                            <option value="email">メール</option>
                        </select>
                        <input
                            type="text"
                            value={newValue}
                            onChange={e => setNewValue(e.target.value)}
                            placeholder={newType === 'domain' ? "example.com" : "user@example.com"}
                            className={styles.input}
                        />
                        <button onClick={handleAdd} disabled={loading} className={styles.addBtn}>
                            {loading ? '...' : '追加'}
                        </button>
                    </div>

                    <div className={styles.list}>
                        {items.length === 0 && <div className={styles.empty}>設定された項目はありません。</div>}
                        {items.map(item => (
                            <div key={item.id} className={styles.item}>
                                <span className={styles.typeBadge}>{item.type}</span>
                                <span className={styles.value}>{item.value}</span>
                                <button onClick={() => handleDelete(item.id)} className={styles.deleteBtn}>削除</button>
                            </div>
                        ))}
                    </div>
                </div>
            </div>
        </div>
    );
}
