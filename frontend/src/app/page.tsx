'use client';
import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import styles from './page.module.css';
import SettingsModal from './SettingsModal';


interface Thread {
  id: number;
  subject: string;
  sender_name: string;
  date: string;
  body: string;
  score: number;
  message_count: number;
  is_high_value: boolean;
  value_score: number;
  originalIndex?: number;
}

interface ContactThreadStub {
  id: number;
  subject: string;
  score: number;
  last_message_at: string;
  message_count: number;
}

interface Contact {
  id: number;
  name: string;
  email: string;
  max_score: number;
  thread_count: number;
  last_active: string | null;
  first_active: string | null;
  top_thread_title: string;
  threads: ContactThreadStub[];
}

export default function Home() {
  const router = useRouter();

  // Data States
  const [contacts, setContacts] = useState<Contact[]>([]);
  const [totalContacts, setTotalContacts] = useState(0);
  const [offset, setOffset] = useState(0);
  const [hasMore, setHasMore] = useState(true);
  const [threads, setThreads] = useState<Thread[]>([]); // For search results

  // UI States
  const [loading, setLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState('');
  const [isSearching, setIsSearching] = useState(false);
  const [expandedContactId, setExpandedContactId] = useState<number | null>(null);
  const [showSettings, setShowSettings] = useState(false);


  // Initial Load (Contacts)
  useEffect(() => {
    fetchStats();
    fetchContacts(0, true);

    // Restore scroll
    const savedScroll = sessionStorage.getItem('scrollPos');
    if (savedScroll) {
      requestAnimationFrame(() => {
        window.scrollTo(0, parseInt(savedScroll));
        sessionStorage.removeItem('scrollPos');
      });
    }
  }, []);

  const fetchStats = () => {
    fetch('http://localhost:8000/stats')
      .then(res => res.json())
      .then(data => {
        // This is raw total, but our list is 'active' contacts.
        // Ideally we should know active count. For now, show total known.
        setTotalContacts(data.contacts);
      })
      .catch(console.error);
  };

  const fetchContacts = (currentOffset = 0, reset = false) => {
    if (reset) setLoading(true);
    const limit = 50;
    fetch(`http://localhost:8000/contacts?limit=${limit}&offset=${currentOffset}`)
      .then(res => res.json())
      .then(data => {
        if (reset) {
          setContacts(data);
          setLoading(false);
        } else {
          setContacts(prev => [...prev, ...data]);
        }

        if (data.length < limit) {
          setHasMore(false);
        } else {
          setHasMore(true);
        }

        setOffset(currentOffset + limit);
      })
      .catch(err => {
        console.error(err);
        setLoading(false);
      });
  };

  const handleLoadMore = () => {
    fetchContacts(offset, false);
  };


  const performSearch = (query: string) => {
    if (!query.trim()) {
      setIsSearching(false);
      fetchContacts(0, true); // Revert to contacts view
      return;
    }

    setIsSearching(true);
    setLoading(true);
    // Use existing search endpoint (returns threads)
    fetch(`http://localhost:8000/search?q=${encodeURIComponent(query)}&limit=20`)
      .then(res => res.json())
      .then(data => {
        // Map to Thread interface
        const results = data.map((item: any, index: number) => ({
          id: item.thread_id,
          subject: item.subject || "(No Subject)",
          sender_name: item.sender || "Unknown",
          date: item.date,
          body: item.body || "",
          score: item.score,
          message_count: 0, // Not provided by current search API
          is_high_value: false, // Not provided
          value_score: 0,
          originalIndex: index
        }));

        // Dedup
        const uniqueResults = Array.from(new Map(results.map((item: any) => [item.id, item])).values());
        setThreads(uniqueResults as Thread[]);
        setLoading(false);
      })
      .catch(err => {
        console.error(err);
        setLoading(false);
      });
  };

  // Debounced Search
  useEffect(() => {
    const timer = setTimeout(() => {
      if (searchQuery) {
        performSearch(searchQuery);
      } else if (isSearching) {
        // Query cleared but state says searching -> revert
        setIsSearching(false);
        fetchContacts(0, true);
      }
    }, 500);
    return () => clearTimeout(timer);
  }, [searchQuery]);

  const toggleContact = (id: number, e: React.MouseEvent) => {
    e.stopPropagation();
    setExpandedContactId(expandedContactId === id ? null : id);
  };

  const handleThreadClick = (threadId: number) => {
    sessionStorage.setItem('scrollPos', window.scrollY.toString());
    router.push(`/thread/${threadId}`);
  };

  const handleIgnore = async (value: string, type: 'email' | 'domain', e: React.MouseEvent) => {
    e.stopPropagation();
    // if (!confirm(`Hide ${type} "${value}" from future lists?`)) return;

    try {
      const res = await fetch('http://localhost:8000/settings/ignore', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ value, type })
      });
      if (res.ok) {
        // Remove from local state immediately to avoid reload/scroll jump
        setContacts(prev => prev.filter(c => {
          if (type === 'email') return c.email !== value;
          if (type === 'domain') return !c.email.endsWith(`@${value}`);
          return true;
        }));
        // Silently update total count
        fetchStats();
      } else {
        alert('Failed to save setting.');
      }
    } catch (error) {
      console.error(error);
      alert('Error saving setting.');
    }
  };


  const [sortByScore, setSortByScore] = useState(false);

  // Sort threads based on toggle
  const displayThreads = [...threads].sort((a, b) => {
    if (sortByScore) {
      return (b.score || 0) - (a.score || 0);
    }
    return (a.originalIndex ?? 0) - (b.originalIndex ?? 0);
  });

  return (
    <main className={styles.main}>
      <header className={styles.header}>
        <div className={styles.brand} onClick={() => { setSearchQuery(''); setIsSearching(false); fetchContacts(0, true); }} style={{ cursor: 'pointer' }}>
          <img src="/logo.png" alt="PastLead" className={styles.logoImage} />
          <span className={styles.badge}>Beta</span>
        </div>
        <div className={styles.stats}>
          <div className={styles.statItem}>
            <span className={styles.statLabel}>Contacts</span>
            <span className={styles.statValue}>
              {isSearching ? '-' : `${contacts.length} / ${totalContacts}`}
            </span>
          </div>
          <button className={styles.settingsBtn} onClick={() => setShowSettings(true)} title="Settings">
            ⚙️
          </button>
        </div>
      </header>

      <SettingsModal isOpen={showSettings} onClose={() => { setShowSettings(false); fetchContacts(0, true); }} />


      <div className={styles.container}>

        <div className={styles.searchSection}>
          <div className={styles.searchForm}>
            <input
              type="text"
              className={styles.searchInput}
              placeholder="会話を検索..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
            />
          </div>
        </div>

        <div className={styles.sectionHeader}>
          <h2>{isSearching ? '検索結果 (スレッド)' : '注目の連絡先'}</h2>
          {isSearching && (
            <div className={styles.actions}>
              <label className={styles.toggleContainer}>
                <span style={{ color: sortByScore ? '#60a5fa' : 'inherit', fontWeight: sortByScore ? 600 : 400 }}>High Score</span>
                <input
                  type="checkbox"
                  className={styles.toggleInput}
                  checked={sortByScore}
                  onChange={(e) => setSortByScore(e.target.checked)}
                />
                <div className={styles.toggleSwitch}></div>
              </label>
            </div>
          )}
        </div>

        {loading ? (
          <div className={styles.loading}>Loading...</div>
        ) : isSearching ? (
          /* --- Thread List View (Search Results) --- */
          <div className={styles.messageList}>
            {displayThreads.map(thread => (
              <div key={thread.id} className={`${styles.messageItem} ${thread.is_high_value ? styles.highValue : ''}`} onClick={() => handleThreadClick(thread.id)}>
                <div className={styles.cardHeader}>
                  <div className={styles.scoreBadge} title="AI Priority Score">
                    {thread.score ? thread.score.toFixed(1) : '0.0'}
                  </div>
                  <div className={styles.metaInfo}>
                    <span className={styles.sender}>{thread.sender_name}</span>
                    <span className={styles.date}>{new Date(thread.date).toLocaleDateString()}</span>
                  </div>
                </div>
                <div className={styles.subject}>{thread.subject}</div>
              </div>
            ))}
          </div>
        ) : (
          /* --- Contact List View (Default) --- */
          <div className={styles.contactList}>
            {contacts.map(contact => (
              <div key={contact.id} className={`${styles.contactCard} ${expandedContactId === contact.id ? styles.expanded : ''}`}>
                <div className={styles.contactHeader} onClick={(e) => toggleContact(contact.id, e)}>
                  <div className={styles.contactProfile}>
                    <div className={styles.contactName}>{contact.name}</div>
                    <div className={styles.contactEmailRow}>
                      <div className={styles.contactEmail}>{contact.email}</div>
                      <div className={styles.ignoreActions}>
                        <button
                          className={styles.ignoreBtn}
                          title="Hide this specific email address"
                          onClick={(e) => handleIgnore(contact.email, 'email', e)}
                        >
                          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                            <path d="M16 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"></path>
                            <circle cx="8.5" cy="7" r="4"></circle>
                            <line x1="18" y1="8" x2="23" y2="13"></line>
                            <line x1="23" y1="8" x2="18" y2="13"></line>
                          </svg>
                        </button>
                        <button
                          className={styles.ignoreBtn}
                          title="Hide this entire domain"
                          onClick={(e) => {
                            const domain = contact.email.split('@')[1];
                            if (domain) handleIgnore(domain, 'domain', e);
                          }}
                        >
                          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                            <path d="M3 21h18" />
                            <path d="M5 21V7l8-4 8 4v14" />
                            <path d="M17 10v4" />
                            <path d="M7 10v4" />
                            <line x1="10" y1="9" x2="14" y2="13"></line>
                            <line x1="14" y1="9" x2="10" y2="13"></line>
                          </svg>
                        </button>
                      </div>
                    </div>
                  </div>


                  <div className={styles.statBlock}>
                    <span className={styles.statLabel}>Max Score</span>
                    <span className={`${styles.statValue} ${styles.scoreValue}`}>{contact.max_score.toFixed(1)}</span>
                  </div>

                  <div className={styles.statBlock}>
                    <span className={styles.statLabel}>Last</span>
                    <span className={styles.statValue}>{contact.last_active || '-'}</span>
                  </div>

                  <div className={styles.statBlock}>
                    <span className={styles.statLabel}>First</span>
                    <span className={styles.statValue}>{contact.first_active || '-'}</span>
                  </div>

                  <div className={styles.statBlock}>
                    <span className={styles.statLabel}>Threads</span>
                    <span className={styles.statValue}>{contact.thread_count}</span>
                  </div>

                  <div className={styles.expandIcon}>▼</div>
                </div>

                {expandedContactId === contact.id && (
                  <div className={styles.threadListContainer}>
                    {contact.threads.map(thread => (
                      <div key={thread.id} className={styles.threadRow} onClick={() => handleThreadClick(thread.id)}>
                        <div className={styles.threadScore}>{thread.score.toFixed(1)}</div>
                        <div className={styles.threadSubject}>{thread.subject}</div>
                        <div className={styles.threadDate}>{thread.last_message_at}</div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            ))}
            {hasMore && (
              <div style={{ textAlign: 'center', margin: '2rem 0' }}>
                <button
                  onClick={handleLoadMore}
                  style={{
                    background: '#27272a',
                    border: '1px solid #3f3f46',
                    color: '#e4e4e7',
                    padding: '0.8rem 2rem',
                    borderRadius: '99px',
                    cursor: 'pointer',
                    fontSize: '0.9rem'
                  }}
                >
                  Load More
                </button>
              </div>
            )}
          </div>
        )}
      </div>
    </main>
  );
}
