import React, { useEffect, useMemo, useState } from 'react';
import { createRoot } from 'react-dom/client';
import {
  Alert, AppBar, Avatar, Box, Button, Card, CardContent, Chip, Container, CssBaseline,
  Dialog, DialogActions, DialogContent, DialogTitle, Divider, FormControl, IconButton, InputLabel,
  LinearProgress, Menu, MenuItem, Paper, Select, Stack,
  TextField, ThemeProvider, Toolbar, Tooltip, Typography, createTheme
} from '@mui/material';
import {
  Add, ArrowBack, ArrowForward, AutoAwesome, BrightnessAuto, DarkMode,
  LightMode, CalendarMonth, Campaign, CheckCircle, ContentCopy, Groups, InfoOutlined,
  Launch, MoreHoriz, YouTube, Download
} from '@mui/icons-material';

const seedCampaigns = [];

const youtubeVideoId = rawUrl => {
  try {
    const url = new URL(rawUrl);
    const host = url.hostname.replace(/^www\./, '').toLowerCase();
    let id = '';
    if (host === 'youtu.be') id = url.pathname.split('/').filter(Boolean)[0] || '';
    else if (['youtube.com', 'm.youtube.com', 'youtube-nocookie.com'].includes(host)) {
      const parts = url.pathname.split('/').filter(Boolean);
      const videoPart = parts.findIndex(part => ['shorts', 'embed', 'live'].includes(part));
      id = url.searchParams.get('v') || (videoPart >= 0 ? parts[videoPart + 1] : '');
    }
    return /^[A-Za-z0-9_-]{11}$/.test(id || '') ? id : '';
  } catch { return ''; }
};
const sentenceParts = {
  determiner: ['a', 'each', 'every', 'one', 'the'],
  adjective: ['amber', 'ancient', 'bright', 'brave', 'calm', 'careful', 'cheerful', 'clever', 'curious', 'daring', 'eager', 'gentle', 'golden', 'graceful', 'happy', 'honest', 'humble', 'kind', 'lively', 'little', 'lucky', 'mellow', 'merry', 'mindful', 'nimble', 'noble', 'patient', 'peaceful', 'playful', 'quiet', 'radiant', 'ready', 'rustic', 'safe', 'secret', 'serene', 'silent', 'simple', 'sleepy', 'smooth', 'soft', 'steady', 'sunny', 'tender', 'tiny', 'tranquil', 'vivid', 'warm', 'wild', 'wise', 'young', 'zesty'],
  subject: ['artist', 'author', 'badger', 'baker', 'bird', 'child', 'dancer', 'dreamer', 'eagle', 'farmer', 'fox', 'friend', 'gardener', 'hiker', 'horse', 'kitten', 'lamb', 'learner', 'lion', 'musician', 'otter', 'owl', 'painter', 'panda', 'person', 'poet', 'puppy', 'rabbit', 'reader', 'robin', 'sailor', 'singer', 'sparrow', 'student', 'swan', 'teacher', 'turtle', 'traveler', 'wolf', 'writer', 'dolphin'],
  verb: ['dances', 'drifts', 'explores', 'follows', 'gathers', 'glides', 'listens', 'lingers', 'looks', 'moves', 'plays', 'rests', 'returns', 'rises', 'roams', 'sails', 'searches', 'settles', 'sings', 'sleeps', 'smiles', 'steps', 'swims', 'thinks', 'travels', 'turns', 'ventures', 'waits', 'wakes', 'wanders', 'watches', 'weaves', 'learns', 'laughs', 'walks', 'runs', 'climbs', 'strolls', 'floats', 'hides'],
  adverb: ['boldly', 'bravely', 'calmly', 'carefully', 'cheerfully', 'clearly', 'eagerly', 'freely', 'gently', 'gladly', 'happily', 'honestly', 'kindly', 'lightly', 'loudly', 'merrily', 'openly', 'patiently', 'peacefully', 'playfully', 'proudly', 'quickly', 'quietly', 'safely', 'secretly', 'serenely', 'silently', 'slowly', 'smoothly', 'softly', 'steadily', 'sweetly', 'swiftly', 'tenderly', 'warmly', 'wisely', 'wildly'],
  preposition: ['above', 'across', 'along', 'around', 'beneath', 'beside', 'beyond', 'between', 'down', 'inside', 'near', 'over', 'past', 'through', 'toward', 'under', 'within'],
  place: ['beaches', 'bridges', 'canyons', 'caves', 'cities', 'cliffs', 'coastlines', 'corners', 'courtyards', 'deserts', 'fields', 'forests', 'gardens', 'groves', 'harbors', 'hills', 'horizons', 'islands', 'lakes', 'lanterns', 'meadows', 'mountains', 'oceans', 'orchards', 'parks', 'pastures', 'pathways', 'plains', 'roads', 'rooftops', 'rivers', 'seasons', 'shores', 'skies', 'streets', 'streams', 'sunlight', 'towers', 'trails', 'tunnels', 'valleys', 'villages', 'waterfalls', 'waves', 'windows', 'winter', 'woodlands', 'wonders']
};
const makeClaimSentence = () => {
  const random = new Uint32Array(1);
  const choose = words => { window.crypto.getRandomValues(random); return words[random[0] % words.length]; };
  const sentence = [sentenceParts.determiner, sentenceParts.adjective, sentenceParts.subject, sentenceParts.verb, sentenceParts.adverb, sentenceParts.preposition, sentenceParts.place].map(choose);
  sentence[0] = sentence[0][0].toUpperCase() + sentence[0].slice(1);
  return `${sentence.join(' ')}.`;
};
const readUnlockedResources = () => {
  try {
    const value = JSON.parse(sessionStorage.getItem('dropnote-unlocked-resources') || '{}');
    return value && typeof value === 'object' && !Array.isArray(value) ? value : {};
  } catch { return {}; }
};
const readClaimed = () => Object.fromEntries(Object.keys(readUnlockedResources()).map(id => [id, true]));
const campaignIsAvailable = campaign => {
  if (campaign.status !== 'Live' || (campaign.limit && campaign.claimed >= campaign.limit)) return false;
  if (!campaign.ends || campaign.ends === 'No end date') return true;
  const today = new Date();
  const todayIso = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, '0')}-${String(today.getDate()).padStart(2, '0')}`;
  return /^\d{4}-\d{2}-\d{2}$/.test(campaign.ends) && campaign.ends >= todayIso;
};

function App() {
  const [mode, setMode] = useState(() => localStorage.getItem('dropnote-theme') || 'system');
  const [systemDark, setSystemDark] = useState(() => window.matchMedia?.('(prefers-color-scheme: dark)').matches || false);
  const [themeAnchor, setThemeAnchor] = useState(null);
  const [accountAnchor, setAccountAnchor] = useState(null);
  const [campaignMenuAnchor, setCampaignMenuAnchor] = useState(null);
  const [menuCampaign, setMenuCampaign] = useState(null);
  const [editingCampaignId, setEditingCampaignId] = useState(null);
  const [deleteCampaign, setDeleteCampaign] = useState(null);
  const [view, setView] = useState('discover');
  const [currentUser, setCurrentUser] = useState(null);
  const [sharedCampaignId] = useState(() => new URLSearchParams(window.location.search).get('campaign') || '');
  const [campaignLinkNotice, setCampaignLinkNotice] = useState('');
  const [authOpen, setAuthOpen] = useState(false);
  const [authMode, setAuthMode] = useState('login');
  const [inviteCode, setInviteCode] = useState(() => new URLSearchParams(window.location.hash.slice(1)).get('invite') || '');
  const [inviteOpen, setInviteOpen] = useState(false);
  const [inviteEmail, setInviteEmail] = useState('');
  const [inviteUrl, setInviteUrl] = useState('');
  const [inviteBusy, setInviteBusy] = useState(false);
  const [inviteError, setInviteError] = useState('');
  const [authEmail, setAuthEmail] = useState('');
  const [authPassword, setAuthPassword] = useState('');
  const [authBusy, setAuthBusy] = useState(false);
  const [authError, setAuthError] = useState('');
  const [campaigns, setCampaigns] = useState(seedCampaigns);
  const [studioCampaigns, setStudioCampaigns] = useState([]);
  const [selected, setSelected] = useState(null);
  const [unlockedResources, setUnlockedResources] = useState(readUnlockedResources);
  const [claimStep, setClaimStep] = useState(0);
  const [claimCode, setClaimCode] = useState('');
  const [commentText, setCommentText] = useState('');
  const [email, setEmail] = useState('');
  const [claimed, setClaimed] = useState(readClaimed);
  const [filter, setFilter] = useState('All channels');
  const [discoverFilter, setDiscoverFilter] = useState('All channels');
  const [newOpen, setNewOpen] = useState(false);
  const [campaignSaveBusy, setCampaignSaveBusy] = useState(false);
  const [snack, setSnack] = useState('');
  const [verifyBusy, setVerifyBusy] = useState(false);
  const [verifyError, setVerifyError] = useState('');
  const [videoInfo, setVideoInfo] = useState(null);
  const [videoInfoBusy, setVideoInfoBusy] = useState(false);
  const [videoInfoError, setVideoInfoError] = useState('');
  const [newCampaign, setNewCampaign] = useState({ title: '', channel: '', video: '', resource: '', resourceType: 'link', limit: '', ends: '', status: 'Live', description: 'A new creator resource campaign.', handle: '', category: 'New resource', accent: '#777B77', initials: '' });

  useEffect(() => {
    const media = window.matchMedia?.('(prefers-color-scheme: dark)');
    if (!media) return;
    const update = event => setSystemDark(event.matches);
    media.addEventListener?.('change', update);
    return () => media.removeEventListener?.('change', update);
  }, []);
  useEffect(() => {
    if (!inviteCode) return;
    setView('studio'); setAuthMode('signup'); setAuthOpen(true);
    window.history.replaceState({}, '', window.location.pathname + window.location.search);
  }, []);
  useEffect(() => {
    fetch('/api/auth/me').then(r => r.ok ? r.json() : null).then(data => {
      if (data?.authenticated && data.user) setCurrentUser(data.user);
    }).catch(() => {});
  }, []);
  useEffect(() => {
    fetch('/api/campaigns').then(r => r.ok ? r.json() : []).then(rows => {
      const synced = rows.map(r => ({ id: r.campaign_id, title: r.title, channel: r.channel, handle: r.handle === '@creator' ? '' : (r.handle || ''), category: r.category, accent: r.accent, claimed: r.claimed, limit: r.max_claims, ends: r.ends_at, status: r.status, description: r.description, video: r.video_url, initials: r.initials }));
      if (synced.length) setCampaigns(current => [...synced, ...current.filter(c => !synced.some(s => s.id === c.id))]);
      if (sharedCampaignId) {
        const direct = synced.find(c => c.id === sharedCampaignId) || seedCampaigns.find(c => c.id === sharedCampaignId);
        if (!direct || (!campaignIsAvailable(direct) && !unlockedResources[direct.id])) setCampaignLinkNotice('This campaign link is invalid or the drop is no longer available.');
        else { setDiscoverFilter('All channels'); beginClaim(direct); }
      }
    }).catch(() => { if (sharedCampaignId) setCampaignLinkNotice('Could not load this campaign. Please try again.'); });
  }, []);
  useEffect(() => { localStorage.setItem('dropnote-theme', mode); }, [mode]);
  useEffect(() => { localStorage.removeItem('dropnote-claimed'); }, []);

  const isDark = mode === 'dark' || (mode === 'system' && systemDark);
  const theme = useMemo(() => createTheme({
    palette: {
      mode: isDark ? 'dark' : 'light',
      primary: { main: isDark ? '#D8DBD8' : '#3D423E', dark: isDark ? '#C3C8C3' : '#292D2A', contrastText: isDark ? '#202320' : '#FFFFFF' },
      secondary: { main: isDark ? '#B1B5B1' : '#6E736F' },
      background: { default: isDark ? '#171917' : '#F7F7F5', paper: isDark ? '#202320' : '#FFFFFF' },
      text: { primary: isDark ? '#F0F1EF' : '#242724', secondary: isDark ? '#A7ACA7' : '#686E69' },
      divider: isDark ? 'rgba(230,234,230,.12)' : '#E6E8E5',
      success: { main: isDark ? '#B6BDB7' : '#626963' },
    },
    shape: { borderRadius: 12 },
    typography: {
      fontFamily: 'Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
      button: { textTransform: 'none', fontWeight: 650, letterSpacing: 0 },
      h1: { fontWeight: 720, letterSpacing: '-.045em' },
      h2: { fontWeight: 700, letterSpacing: '-.035em' },
      h3: { fontWeight: 680, letterSpacing: '-.025em' },
    },
    components: {
      MuiButton: { styleOverrides: { root: { borderRadius: 9, padding: '9px 15px', boxShadow: 'none' } } },
      MuiPaper: { styleOverrides: { root: { backgroundImage: 'none' } } },
      MuiCard: { styleOverrides: { root: { backgroundImage: 'none' } } },
      MuiAlert: { styleOverrides: {
        root: { borderRadius: 10 },
        standardInfo: { backgroundColor: isDark ? 'rgba(255,255,255,.045)' : '#F0F1EF', color: isDark ? '#D5D8D5' : '#59605B' },
        standardWarning: { backgroundColor: isDark ? 'rgba(255,255,255,.045)' : '#F0F1EF', color: isDark ? '#D5D8D5' : '#59605B' },
        outlinedInfo: { borderColor: isDark ? 'rgba(255,255,255,.13)' : '#E1E3E0', color: isDark ? '#D5D8D5' : '#59605B' },
        outlinedWarning: { borderColor: isDark ? 'rgba(255,255,255,.13)' : '#E1E3E0', color: isDark ? '#D5D8D5' : '#59605B' },
        icon: { color: isDark ? '#AEB4AF' : '#727872' },
      } },
    },
  }), [isDark]);

  const notify = message => { setSnack(message); window.setTimeout(() => setSnack(''), 2800); };
  const copyComment = async (continueToVerify = false) => {
    const text = [commentText.trim(), claimCode].filter(Boolean).join(' ');
    try {
      await navigator.clipboard.writeText(text);
      notify('Your comment and claim sentence were copied. Paste them as a comment on the video.');
      if (continueToVerify) setClaimStep(2);
    } catch { notify('Clipboard unavailable. Allow clipboard access, then try again.'); }
  };
  const copyResourceLink = async () => {
    try { await navigator.clipboard.writeText(selected?.resource || ''); notify('Resource link copied.'); }
    catch { notify('Clipboard unavailable. Copy the link manually.'); }
  };
  const downloadResourceText = () => {
    const text = selected?.resource || '';
    if (!text) { notify('No resource text to save.'); return; }
    const safeTitle = (selected?.title || 'dropnote-resource').replace(/[^\w\- ]+/g, '').trim().slice(0, 60) || 'dropnote-resource';
    const objectUrl = URL.createObjectURL(new Blob([text], { type: 'text/plain;charset=utf-8' }));
    const anchor = document.createElement('a');
    anchor.href = objectUrl; anchor.download = `${safeTitle}.txt`; document.body.appendChild(anchor); anchor.click(); anchor.remove();
    window.setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);
    notify('Resource text saved on your device.');
  };
  const copyResourceText = async () => {
    try { await navigator.clipboard.writeText(selected?.resource || ''); notify('Resource text copied.'); }
    catch { notify('Clipboard unavailable. Select and copy the resource text manually.'); }
  };
  const mapCampaign = r => ({ id: r.campaign_id, title: r.title, channel: r.channel, handle: r.handle === '@creator' ? '' : (r.handle || ''), category: r.category, accent: r.accent, claimed: r.claimed, limit: r.max_claims, ends: r.ends_at, status: r.status, description: r.description, video: r.video_url, initials: r.initials, resourceType: r.resource_type || 'link', resource: r.resource_type === 'text' ? r.resource_text : r.resource_url });
  const loadStudioCampaigns = async () => {
    const response = await fetch('/api/studio/campaigns');
    if (!response.ok) throw new Error('Could not load Studio campaigns. Please sign in again.');
    const rows = (await response.json()).map(mapCampaign);
    setStudioCampaigns(rows);
    setFilter('All channels');
    setCampaigns(current => [...rows, ...current.filter(c => !rows.some(row => row.id === c.id))]);
  };
  const enterStudio = async () => {
    if (!currentUser) { setAuthMode('login'); setAuthError(''); setAuthOpen(true); return; }
    try { await loadStudioCampaigns(); setView('studio'); }
    catch (error) { setAuthError(error.message); setAuthMode('login'); setAuthOpen(true); setCurrentUser(null); }
  };
  const submitAuth = async event => {
    event.preventDefault(); setAuthBusy(true); setAuthError('');
    try {
      const response = await fetch(`/api/auth/${authMode === 'signup' ? 'signup' : 'login'}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email: authEmail.trim(), password: authPassword, ...(authMode === 'signup' ? { inviteCode } : {}) }) });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.detail || 'Sign-in failed. Check your details and try again.');
      await loadStudioCampaigns();
      setCurrentUser(data.user); setAuthOpen(false); setAuthPassword(''); setView('studio'); setInviteCode('');
    } catch (error) { setAuthError(error.message || 'Authentication service is unavailable.'); }
    finally { setAuthBusy(false); }
  };
  const createInvite = async event => {
    event.preventDefault(); setInviteBusy(true); setInviteError('');
    try {
      const response = await fetch('/api/admin/invites', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email: inviteEmail.trim() }) });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.detail || 'Could not create invitation.');
      const url = `${window.location.origin}/#invite=${encodeURIComponent(data.inviteCode)}`;
      setInviteUrl(url); notify(`Invitation created for ${data.email}. It expires in 7 days.`);
    } catch (error) { setInviteError(error.message || 'Could not create invitation.'); }
    finally { setInviteBusy(false); }
  };
  const copyInvite = async () => {
    try { await navigator.clipboard.writeText(inviteUrl); notify('Invitation link copied.'); }
    catch { notify('Clipboard unavailable. Select and copy the invitation link.'); }
  };
  const copyCampaignLink = async () => {
    if (!menuCampaign) return;
    const url = `${window.location.origin}/?campaign=${encodeURIComponent(menuCampaign.id)}`;
    try { await navigator.clipboard.writeText(url); notify('Campaign link copied. It opens directly to this drop.'); }
    catch { notify(`Share this campaign URL: ${url}`); }
    finally { setCampaignMenuAnchor(null); setMenuCampaign(null); }
  };
  const signOut = async () => {
    await fetch('/api/auth/logout', { method: 'POST' }).catch(() => {});
    setCurrentUser(null); setStudioCampaigns([]); setView('discover'); notify('Signed out.');
  };
  const beginClaim = campaign => {
    const unlocked = unlockedResources[campaign.id];
    if (unlocked) {
      setSelected({ ...campaign, ...unlocked }); setClaimStep(3); setVerifyError(''); return;
    }
    if (claimed[campaign.id]) { notify('This browser has already claimed this drop. The resource is available only for the browser session in which it was unlocked.'); return; }
    setSelected(campaign); setClaimStep(1); setClaimCode(makeClaimSentence()); setCommentText(''); setEmail(''); setVerifyError('');
  };
  const closeClaim = () => { setSelected(null); setClaimStep(0); setVerifyError(''); };
  const finishClaim = (incrementClaimCount = true) => {
    setClaimed(current => ({ ...current, [selected.id]: true }));
    if (incrementClaimCount) setCampaigns(items => items.map(item => item.id === selected.id ? { ...item, claimed: item.claimed + 1 } : item));
    setClaimStep(3);
  };
  const verifyComment = async () => {
    if (!selected) return;
    setVerifyBusy(true); setVerifyError('');
    try {
      const response = await fetch('/api/verify', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ campaignId: selected.id, code: claimCode }) });
      const result = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(result.detail || 'Could not verify the comment. Please try again.');
      const unlocked = { resourceType: result.resourceType || 'link', resource: result.resourceType === 'text' ? result.resourceText : result.resourceUrl };
      setSelected(current => ({ ...current, ...unlocked }));
      const nextUnlocked = { ...unlockedResources, [selected.id]: unlocked };
      setUnlockedResources(nextUnlocked);
      try { sessionStorage.setItem('dropnote-unlocked-resources', JSON.stringify(nextUnlocked)); } catch { /* Keep the resource open in memory if session storage is unavailable. */ }
      finishClaim(result.alreadyClaimed !== true);
    } catch (error) { setVerifyError(error.message || 'Verification service is unavailable.'); }
    finally { setVerifyBusy(false); }
  };
  const fetchVideoInfo = async () => {
    if (!newCampaign.video.trim()) return;
    setVideoInfoBusy(true); setVideoInfoError(''); setVideoInfo(null);
    try {
      const response = await fetch('/api/youtube/info', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ video: newCampaign.video.trim() }) });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.detail || 'Could not fetch YouTube video information.');
      setVideoInfo(data);
      setNewCampaign(current => ({ ...current, title: data.title || current.title, channel: data.channel || current.channel, handle: data.handle || '' }));
    } catch (error) { setVideoInfoError(error.message || 'Could not fetch YouTube video information.'); }
    finally { setVideoInfoBusy(false); }
  };
  const blankCampaign = () => ({ title: '', channel: '', video: '', resource: '', resourceType: 'link', limit: '', ends: '', status: 'Live', description: 'A new creator resource campaign.', handle: '', category: 'New resource', accent: '#777B77', initials: '' });
  const openNewCampaign = () => { setEditingCampaignId(null); setNewCampaign(blankCampaign()); setVideoInfo(null); setVideoInfoError(''); setNewOpen(true); };
  const beginEditCampaign = campaign => {
    setCampaignMenuAnchor(null); setMenuCampaign(null); setEditingCampaignId(campaign.id);
    setNewCampaign({ title: campaign.title, channel: campaign.channel, video: campaign.video, resource: campaign.resource || '', resourceType: campaign.resourceType || 'link', limit: campaign.limit || '', ends: campaign.ends === 'No end date' ? '' : campaign.ends, status: campaign.status || 'Live', description: campaign.description || '', handle: campaign.handle === '@creator' ? '' : (campaign.handle || ''), category: campaign.category || 'New resource', accent: campaign.accent || '#777B77', initials: campaign.initials || '' });
    setVideoInfo(null); setVideoInfoError(''); setNewOpen(true);
  };
  const saveCampaign = async () => {
    if (campaignSaveBusy || !newCampaign.title.trim() || !newCampaign.channel.trim() || !newCampaign.video.trim() || !newCampaign.resource.trim()) return;
    setCampaignSaveBusy(true);
    const c = {
      id: editingCampaignId || `new-${Date.now()}`, title: newCampaign.title.trim(), channel: newCampaign.channel.trim(),
      handle: newCampaign.handle || '', category: newCampaign.category || 'New resource', accent: newCampaign.accent || '#777B77', claimed: editingCampaignId ? (studioCampaigns.find(item => item.id === editingCampaignId)?.claimed || 0) : 0,
      limit: newCampaign.limit ? Number(newCampaign.limit) : null,
      ends: newCampaign.ends || 'No end date', status: newCampaign.status || 'Live',
      description: newCampaign.description || 'A new creator resource campaign.', resource: newCampaign.resource.trim(), resourceType: newCampaign.resourceType,
      video: newCampaign.video.trim(), initials: newCampaign.initials || newCampaign.channel.split(' ').map(x => x[0]).join('').slice(0, 2).toUpperCase(),
    };
    try {
      const isEditing = Boolean(editingCampaignId);
      const response = await fetch(isEditing ? `/api/campaigns/${encodeURIComponent(editingCampaignId)}` : '/api/campaigns', { method: isEditing ? 'PUT' : 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(c) });
      const result = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(result.detail || 'Could not save campaign.');
      const saveRows = current => isEditing ? current.map(item => item.id === c.id ? c : item) : [c, ...current];
      setCampaigns(saveRows); setStudioCampaigns(saveRows); setNewCampaign(blankCampaign()); setEditingCampaignId(null); setNewOpen(false); notify(isEditing ? 'Campaign updated.' : 'Campaign saved.');
    } catch (error) {
      notify(error.message || 'Campaign service unavailable.');
    } finally { setCampaignSaveBusy(false); }
  };
  const toggleCampaignStatus = async () => {
    if (!menuCampaign) return;
    const status = menuCampaign.status === 'Live' ? 'Paused' : 'Live';
    try {
      const response = await fetch(`/api/campaigns/${encodeURIComponent(menuCampaign.id)}/status`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ status }) });
      const result = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(result.detail || 'Could not update campaign status.');
      const updateRows = rows => rows.map(item => item.id === menuCampaign.id ? { ...item, status } : item);
      setCampaigns(updateRows); setStudioCampaigns(updateRows); notify(status === 'Paused' ? 'Campaign paused.' : 'Campaign is live again.');
    } catch (error) { notify(error.message || 'Could not update campaign.'); }
    finally { setCampaignMenuAnchor(null); setMenuCampaign(null); }
  };
  const confirmDeleteCampaign = async () => {
    if (!deleteCampaign) return;
    try {
      const response = await fetch(`/api/campaigns/${encodeURIComponent(deleteCampaign.id)}`, { method: 'DELETE' });
      const result = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(result.detail || 'Could not delete campaign.');
      setCampaigns(rows => rows.filter(item => item.id !== deleteCampaign.id));
      setStudioCampaigns(rows => rows.filter(item => item.id !== deleteCampaign.id));
      notify('Campaign deleted.'); setDeleteCampaign(null);
    } catch (error) { notify(error.message || 'Could not delete campaign.'); }
  };
  const studioChannels = ['All channels', ...new Set(studioCampaigns.map(c => c.channel))];
  const filteredStudioCampaigns = studioCampaigns.filter(c => filter === 'All channels' || c.channel === filter);
  const activeCampaigns = campaigns.filter(campaignIsAvailable);
  // Keep this viewer's unlocked drops visible for the remainder of the browser session, even if the last claim filled the cap.
  const discoverCampaigns = campaigns.filter(c => campaignIsAvailable(c) || Boolean(claimed[c.id]));
  const discoverChannels = [...new Set(discoverCampaigns.map(c => c.channel))];
  const filteredDiscoverCampaigns = discoverCampaigns.filter(c => discoverFilter === 'All channels' || c.channel === discoverFilter);
  const totalClaims = studioCampaigns.reduce((sum, c) => sum + c.claimed, 0);
  const progress = campaign => campaign.limit ? Math.min(100, Math.round(campaign.claimed / campaign.limit * 100)) : 0;

  return <ThemeProvider theme={theme}>
    <CssBaseline />
    <AppBar position="sticky" color="inherit" elevation={0} sx={{ borderBottom: 1, borderColor: 'divider', bgcolor: 'background.paper' }}>
      <Container maxWidth="lg" disableGutters>
        <Toolbar disableGutters sx={{ minHeight: 72, px: { xs: 2, md: 0 }, gap: 2, justifyContent: 'space-between' }}>
          <Button onClick={() => setView('discover')} color="inherit" sx={{ p: 0, minWidth: 0, textAlign: 'left', '&:hover': { bgcolor: 'transparent' } }}>
            <Stack direction="row" alignItems="center" spacing={1.15}>
              <Box sx={{ width: 34, height: 34, borderRadius: 1.5, bgcolor: 'primary.main', color: 'primary.contrastText', display: 'grid', placeItems: 'center' }}><AutoAwesome sx={{ fontSize: 19 }} /></Box>
              <Box><Typography sx={{ fontWeight: 780, fontSize: 18, letterSpacing: '-.04em', lineHeight: 1.1 }}>dropnote</Typography><Typography sx={{ fontSize: 10, color: 'text.secondary', letterSpacing: '.09em', textTransform: 'uppercase', mt: .25 }}>Creator drops</Typography></Box>
            </Stack>
          </Button>
          <Stack direction="row" alignItems="center" spacing={{ xs: .25, sm: .75 }}>
            <Button size="small" color={view === 'discover' ? 'primary' : 'inherit'} variant={view === 'discover' ? 'contained' : 'text'} onClick={() => setView('discover')}>Discover</Button>
            <Button size="small" color={view === 'studio' ? 'primary' : 'inherit'} variant={view === 'studio' ? 'contained' : 'text'} onClick={enterStudio}>Studio</Button>
            {currentUser && <>
              <Tooltip title={currentUser.email}><IconButton aria-label="Account menu" onClick={e => setAccountAnchor(e.currentTarget)} size="small"><Avatar sx={{ width: 30, height: 30, fontSize: 12, bgcolor: 'action.hover', color: 'text.primary' }}>{currentUser.email.slice(0, 1).toUpperCase()}</Avatar></IconButton></Tooltip>
              <Menu anchorEl={accountAnchor} open={Boolean(accountAnchor)} onClose={() => setAccountAnchor(null)} MenuListProps={{ 'aria-label': 'Account options' }}>
                <MenuItem disabled>{currentUser.email}</MenuItem><Divider /><MenuItem onClick={() => { setAccountAnchor(null); signOut(); }}>Sign out</MenuItem>
              </Menu>
            </>}
            <Tooltip title={`Theme: ${mode === 'system' ? 'System' : mode === 'light' ? 'Light' : 'Dark'}`}>
              <IconButton aria-label="Color theme" aria-haspopup="menu" onClick={e => setThemeAnchor(e.currentTarget)} size="small" sx={{ ml: { xs: .25, sm: .75 }, width: 36, height: 36, color: 'text.secondary' }}>
                {mode === 'system' ? <BrightnessAuto fontSize="small" /> : mode === 'light' ? <LightMode fontSize="small" /> : <DarkMode fontSize="small" />}
              </IconButton>
            </Tooltip>
            <Menu anchorEl={themeAnchor} open={Boolean(themeAnchor)} onClose={() => setThemeAnchor(null)} MenuListProps={{ 'aria-label': 'Choose color theme' }}>
              <MenuItem selected={mode === 'system'} onClick={() => { setMode('system'); setThemeAnchor(null); }}>System</MenuItem>
              <MenuItem selected={mode === 'light'} onClick={() => { setMode('light'); setThemeAnchor(null); }}>Light</MenuItem>
              <MenuItem selected={mode === 'dark'} onClick={() => { setMode('dark'); setThemeAnchor(null); }}>Dark</MenuItem>
            </Menu>
          </Stack>
        </Toolbar>
      </Container>
    </AppBar>

    <Container maxWidth="lg" sx={{ px: { xs: 2, md: 0 }, pb: 7 }}>
      {view === 'discover' && <>
        {campaignLinkNotice && <Alert severity="warning" sx={{ mt: 2 }}>{campaignLinkNotice}</Alert>}
        <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', md: '1.2fr .8fr' }, gap: { xs: 4, md: 7 }, alignItems: 'center', py: { xs: 5, md: 7 } }}>
          <Box>
            <Chip icon={<AutoAwesome sx={{ fontSize: '16px !important' }} />} label="A little extra from creators" size="small" variant="outlined" sx={{ mb: 2, borderColor: 'divider', color: 'text.secondary', bgcolor: 'background.paper', fontWeight: 600 }} />
            <Typography variant="h1" sx={{ fontSize: { xs: 39, sm: 50, md: 58 }, lineHeight: 1.05, maxWidth: 650 }}>Good work deserves a little <Box component="span" sx={{ color: 'primary.main' }}>something extra.</Box></Typography>
            <Typography color="text.secondary" sx={{ mt: 2, maxWidth: 570, fontSize: { xs: 16, md: 17 }, lineHeight: 1.75 }}>Find useful resources from creators you follow. Leave a genuine comment in your own words, then unlock the extra they made for their community.</Typography>
            <Stack direction="row" spacing={1.25} alignItems="center" sx={{ mt: 3 }}>
              <Button variant="contained" endIcon={<ArrowForward />} onClick={() => document.getElementById('drops')?.scrollIntoView({ behavior: 'smooth' })}>Explore drops</Button>
              <Typography variant="caption" color="text.secondary">{activeCampaigns.length} active campaigns</Typography>
            </Stack>
          </Box>
          <Paper variant="outlined" sx={{ borderRadius: 3, p: { xs: 2.5, md: 3 }, bgcolor: 'background.paper' }}>
            <Stack direction="row" spacing={1.25} alignItems="center" sx={{ mb: 2.5 }}><Box sx={{ display: 'grid', placeItems: 'center', width: 38, height: 38, borderRadius: 1.5, bgcolor: 'action.hover', color: 'primary.main' }}><Campaign fontSize="small" /></Box><Box><Typography fontWeight={700}>How a drop works</Typography><Typography variant="caption" color="text.secondary">A simple way to share something useful</Typography></Box></Stack>
            {[['01', 'Choose a resource', 'Find a guide, template, or other creator extra.'], ['02', 'Write your comment', 'Say what you think. A unique claim sentence is added when you copy.'], ['03', 'Get the link', 'Once your public comment is found, the resource is yours.']].map(([n, title, desc], i) => <Stack key={n} direction="row" spacing={1.5} sx={{ py: 1.55, borderTop: i ? 1 : 0, borderColor: 'divider' }}><Typography sx={{ fontSize: 12, color: 'primary.main', fontWeight: 750, pt: .2 }}>{n}</Typography><Box><Typography variant="body2" fontWeight={680}>{title}</Typography><Typography variant="caption" color="text.secondary" sx={{ lineHeight: 1.55 }}>{desc}</Typography></Box></Stack>)}
          </Paper>
        </Box>

        <Box id="drops" sx={{ pt: 1 }}>
          <Stack direction={{ xs: 'column', sm: 'row' }} alignItems={{ xs: 'flex-start', sm: 'end' }} justifyContent="space-between" spacing={2} sx={{ mb: 2.5 }}>
            <Box><Typography variant="h2" sx={{ fontSize: 27 }}>Available drops</Typography><Typography variant="body2" color="text.secondary" sx={{ mt: .5 }}>Small, useful extras shared by the people who made them.</Typography></Box>
            <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1.25} alignItems={{ xs: 'stretch', sm: 'center' }}>
              <FormControl size="small" sx={{ minWidth: 190 }}><InputLabel id="discover-channel-filter-label">Channel</InputLabel><Select labelId="discover-channel-filter-label" label="Channel" value={discoverFilter} onChange={e => setDiscoverFilter(e.target.value)}><MenuItem value="All channels">All channels</MenuItem>{discoverChannels.map(channel => <MenuItem key={channel} value={channel}>{channel}</MenuItem>)}</Select></FormControl>
              <Chip icon={<Groups sx={{ fontSize: '16px !important' }} />} label={`${filteredDiscoverCampaigns.length} drops`} variant="outlined" sx={{ borderColor: 'divider', bgcolor: 'background.paper' }} />
            </Stack>
          </Stack>
          <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', sm: 'repeat(2, 1fr)', lg: 'repeat(3, 1fr)' }, gridAutoRows: '1fr', gap: 2 }}>
            {filteredDiscoverCampaigns.length ? filteredDiscoverCampaigns.map(c => <DropCard key={c.id} campaign={c} onOpen={() => beginClaim(c)} progress={progress(c)} claimed={Boolean(claimed[c.id])} />) : <Paper variant="outlined" sx={{ gridColumn: '1 / -1', width: '100%', minHeight: { xs: 190, sm: 220 }, boxSizing: 'border-box', p: { xs: 3, sm: 4 }, borderRadius: 2.5, borderStyle: 'dashed', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', textAlign: 'center' }}><Box sx={{ width: 42, height: 42, mb: 1.5, borderRadius: '50%', bgcolor: 'action.hover', color: 'text.secondary', display: 'grid', placeItems: 'center' }}><Campaign sx={{ fontSize: 21 }} /></Box><Typography fontWeight={650}>{discoverFilter === 'All channels' ? 'No drops available just yet.' : 'No drops for this channel yet.'}</Typography><Typography variant="body2" color="text.secondary" sx={{ mt: .6, maxWidth: 360 }}>{discoverFilter === 'All channels' ? 'Creator resources will appear here as soon as a drop goes live.' : `There are no live drops from ${discoverFilter} right now.`}</Typography>{discoverFilter !== 'All channels' && <Button size="small" sx={{ mt: 1.25 }} onClick={() => setDiscoverFilter('All channels')}>Show all channels</Button>}</Paper>}
          </Box>
          <Alert icon={<InfoOutlined fontSize="small" />} severity="info" variant="outlined" sx={{ mt: 3, borderColor: 'divider', bgcolor: 'transparent', color: 'text.secondary', '& .MuiAlert-icon': { color: 'primary.main' } }}>
            <Typography variant="caption">Early prototype: comment checks use a best-effort community scraper and may fail when YouTube changes its systems. Please leave genuine comments; this demo is not production verification.</Typography>
          </Alert>
        </Box>
      </>}

      {view === 'studio' && !currentUser && <>
        <PageHeading eyebrow="Creator workspace" title="Sign in to Studio" description="Sign in to manage your creator campaigns. Creator access is by invitation only." action={<Button variant="contained" onClick={() => { setAuthMode('login'); setAuthOpen(true); }}>Sign in</Button>} />
        <Paper variant="outlined" sx={{ p: { xs: 3, md: 5 }, maxWidth: 680, borderRadius: 3 }}>
          <Typography variant="h5" fontWeight={700}>Your campaigns, in one place</Typography>
          <Typography color="text.secondary" sx={{ mt: 1, maxWidth: 540 }}>Create resource drops, set claim limits and end dates, and see campaign activity. Ask your Dropnote administrator for an invitation if you need an account.</Typography>
          <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1.25} sx={{ mt: 2.5 }}>
            <Button variant="contained" onClick={() => { setAuthMode('login'); setAuthError(''); setAuthOpen(true); }}>Sign in</Button>
          </Stack>
        </Paper>
      </>}

      {view === 'studio' && currentUser && <>
        <PageHeading eyebrow={currentUser.role === 'admin' ? 'Administrator' : 'Creator workspace'} title="Studio" description={currentUser.role === 'admin' ? 'Review campaigns across creator accounts.' : 'Manage your resource campaigns and see how they’re doing.'} action={<Stack direction="row" spacing={1} alignItems="center">{currentUser.role === 'admin' && <Button variant="outlined" onClick={() => { setInviteOpen(true); setInviteError(''); setInviteEmail(''); setInviteUrl(''); }}>Invite creator</Button>}<Button variant="contained" startIcon={<Add />} onClick={openNewCampaign}>New campaign</Button></Stack>} />
        {currentUser.role === 'admin' && <Alert severity="info" variant="outlined" sx={{ mb: 2, borderColor: 'divider' }}>Administrator access is configured on the server with DROPNOTE_ADMIN_EMAIL and DROPNOTE_ADMIN_PASSWORD environment variables.</Alert>}
        <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', sm: 'repeat(3, 1fr)' }, gap: 1.5, mb: 3 }}>
          <Metric label="Campaigns" value={studioCampaigns.filter(c => c.status === 'Live').length} note="Visible in this workspace" icon={<Campaign fontSize="small" />} />
          <Metric label="Total claims" value={totalClaims.toLocaleString()} note="Across these campaigns" icon={<CheckCircle fontSize="small" />} />
          <Metric label="Channels" value={new Set(studioCampaigns.map(c => c.channel)).size} note="In this workspace" icon={<YouTube fontSize="small" />} />
        </Box>
        <Paper variant="outlined" sx={{ borderRadius: 3, overflow: 'hidden' }}>
          <Stack direction={{ xs: 'column', sm: 'row' }} alignItems={{ xs: 'stretch', sm: 'center' }} justifyContent="space-between" spacing={1.5} sx={{ px: 2.5, py: 2 }}>
            <Box><Typography fontWeight={720}>{currentUser.role === 'admin' ? 'All campaigns' : 'Your campaigns'}</Typography><Typography variant="caption" color="text.secondary">Filter by channel to find a specific drop.</Typography></Box>
            <FormControl size="small" sx={{ minWidth: 185 }}><InputLabel>Channel</InputLabel><Select value={filter} label="Channel" onChange={e => setFilter(e.target.value)}>{studioChannels.map(c => <MenuItem key={c} value={c}>{c}</MenuItem>)}</Select></FormControl>
          </Stack>
          <Divider />
          {filteredStudioCampaigns.length ? filteredStudioCampaigns.map((c, i) => <Box key={c.id} sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', sm: 'minmax(220px, 1.5fr) minmax(160px, 1fr)', md: 'minmax(220px, 1.6fr) minmax(150px, 1fr) minmax(120px, .7fr) 112px' }, gap: 2, alignItems: 'center', px: 2.5, py: 2, borderBottom: i < filteredStudioCampaigns.length - 1 ? 1 : 0, borderColor: 'divider' }}>
            <Stack direction="row" alignItems="center" spacing={1.5}>{youtubeVideoId(c.video) ? <Box component="img" src={`https://i.ytimg.com/vi/${youtubeVideoId(c.video)}/hqdefault.jpg`} alt={`${c.title} video thumbnail`} loading="lazy" onError={e => { e.currentTarget.style.display = 'none'; }} sx={{ width: 64, height: 42, flexShrink: 0, borderRadius: 1.25, bgcolor: 'action.hover', objectFit: 'cover' }} /> : <Avatar variant="rounded" sx={{ width: 42, height: 42, bgcolor: 'action.hover', color: 'text.secondary', fontSize: 13, fontWeight: 700 }}>{c.initials}</Avatar>}<Box sx={{ minWidth: 0 }}><Typography variant="body2" fontWeight={700}>{c.title}</Typography><Typography variant="caption" color="text.secondary">{c.channel} · {c.category}</Typography></Box></Stack>
            <Box><Stack direction="row" justifyContent="space-between" sx={{ mb: .6 }}><Typography variant="caption" color="text.secondary">Claims</Typography><Typography variant="caption" fontWeight={650}>{c.claimed}{c.limit ? ` / ${c.limit}` : ''}</Typography></Stack><LinearProgress variant="determinate" value={c.limit ? progress(c) : Math.min(100, c.claimed)} sx={{ height: 5, borderRadius: 5, bgcolor: 'action.hover' }} /></Box>
            <Stack direction="row" spacing={.7} alignItems="center" color="text.secondary"><CalendarMonth sx={{ fontSize: 15 }} /><Typography variant="caption">Ends {c.ends}</Typography></Stack>
            <Stack direction="row" alignItems="center" justifyContent="space-between" sx={{ width: '100%' }}><Chip size="small" label={c.status} variant="outlined" /><Tooltip title="Campaign actions"><IconButton aria-label={`Actions for ${c.title}`} size="small" onClick={e => { setCampaignMenuAnchor(e.currentTarget); setMenuCampaign(c); }}><MoreHoriz fontSize="small" /></IconButton></Tooltip></Stack>
          </Box>) : <Box sx={{ p: 4, textAlign: 'center' }}><Typography fontWeight={650}>No campaigns yet</Typography><Typography variant="body2" color="text.secondary" sx={{ mt: .5 }}>Create your first resource drop to get started.</Typography><Button sx={{ mt: 1.5 }} startIcon={<Add />} onClick={openNewCampaign}>Create a campaign</Button></Box>}
        </Paper>
      </>}
    </Container>

    <Menu anchorEl={campaignMenuAnchor} open={Boolean(campaignMenuAnchor)} onClose={() => { setCampaignMenuAnchor(null); setMenuCampaign(null); }}>
      <MenuItem onClick={copyCampaignLink}>Copy campaign link</MenuItem>
      <MenuItem onClick={() => menuCampaign && beginEditCampaign(menuCampaign)}>Edit campaign</MenuItem>
      <MenuItem onClick={toggleCampaignStatus}>{menuCampaign?.status === 'Live' ? 'Pause campaign' : 'Resume campaign'}</MenuItem>
      <MenuItem onClick={() => { setCampaignMenuAnchor(null); setDeleteCampaign(menuCampaign); setMenuCampaign(null); }}>Delete campaign</MenuItem>
    </Menu>
    <Dialog open={Boolean(deleteCampaign)} onClose={() => setDeleteCampaign(null)} fullWidth maxWidth="xs">
      <DialogTitle sx={{ fontWeight: 720 }}>Delete campaign?</DialogTitle>
      <DialogContent><Typography variant="body2" color="text.secondary">“{deleteCampaign?.title}” and its claim records will be permanently deleted. This can’t be undone.</Typography></DialogContent>
      <DialogActions sx={{ p: 2 }}><Button onClick={() => setDeleteCampaign(null)}>Cancel</Button><Button color="error" variant="contained" onClick={confirmDeleteCampaign}>Delete</Button></DialogActions>
    </Dialog>

    <Box component="footer" sx={{ borderTop: 1, borderColor: 'divider', bgcolor: 'background.paper' }}><Container maxWidth="lg" sx={{ px: { xs: 2, md: 0 }, py: 2.25, display: 'flex', justifyContent: 'space-between', flexWrap: 'wrap', gap: 1 }}><Typography variant="caption" color="text.secondary">© 2026 Dropnote</Typography><Typography variant="caption" color="text.secondary">A simple prototype for creator communities</Typography></Container></Box>

    <Dialog open={authOpen} onClose={() => { if (!authBusy) { setAuthOpen(false); setAuthError(''); } }} fullWidth maxWidth="xs" PaperProps={{ sx: { borderRadius: 3 } }}>
      <Box component="form" onSubmit={submitAuth}>
        <DialogTitle sx={{ fontWeight: 720 }}>{authMode === 'signup' ? 'Accept creator invitation' : 'Sign in to Studio'}</DialogTitle>
        <DialogContent>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>{authMode === 'signup' ? 'This invitation is single-use and tied to the email address approved by your administrator.' : 'Use your creator account to manage campaigns. Admin access uses the server-configured credentials.'}</Typography>
          <Stack spacing={1.75}>
            {authMode === 'signup' && <TextField label="Invitation code" value={inviteCode} onChange={e => setInviteCode(e.target.value)} required fullWidth sx={{ '& .MuiOutlinedInput-root.Mui-focused .MuiOutlinedInput-notchedOutline': { borderColor: 'divider' }, '& .MuiInputLabel-root.Mui-focused': { color: 'text.secondary' } }} />}
            <TextField label="Email" type="email" value={authEmail} onChange={e => setAuthEmail(e.target.value)} autoComplete="email" required fullWidth />
            <TextField label="Password" type="password" value={authPassword} onChange={e => setAuthPassword(e.target.value)} autoComplete={authMode === 'signup' ? 'new-password' : 'current-password'} required inputProps={{ minLength: 8, maxLength: 128 }} helperText={authMode === 'signup' ? 'Use at least 8 characters.' : undefined} fullWidth />
            {authError && <Alert severity="error">{authError}</Alert>}
            {authMode === 'login' && <Typography variant="caption" color="text.secondary">Admin sign-in is managed with server environment variables. Creator accounts require an invitation from an administrator.</Typography>}
          </Stack>
        </DialogContent>
        <DialogActions sx={{ px: 3, pb: 2.5, justifyContent: 'space-between' }}>
          {authMode === 'signup' && <Button size="small" onClick={() => { setAuthMode('login'); setAuthError(''); setInviteCode(''); }}>{'Already have an account? Sign in'}</Button>}
          <Button type="submit" variant="contained" disabled={authBusy || (authMode === 'signup' && !inviteCode.trim())}>{authBusy ? 'Please wait…' : authMode === 'signup' ? 'Accept invitation' : 'Sign in'}</Button>
        </DialogActions>
      </Box>
    </Dialog>

    <Dialog open={Boolean(selected)} onClose={closeClaim} fullWidth maxWidth="sm" PaperProps={{ tabIndex: -1, sx: { borderRadius: 3, '&:focus': { outline: 'none' }, '&:focus-visible': { outline: '2px solid', outlineColor: 'divider', outlineOffset: '-2px' } } }}>
      <DialogTitle sx={{ display: 'flex', alignItems: 'center', gap: 1, fontWeight: 720, pb: 1 }}>{claimStep < 3 && <IconButton size="small" aria-label="Back" onClick={() => claimStep === 2 ? setClaimStep(1) : closeClaim()}><ArrowBack fontSize="small" /></IconButton>}{claimStep === 1 ? 'Get this drop' : claimStep === 2 ? 'Check your comment' : 'Your resource is ready'}</DialogTitle>
      <DialogContent dividers>
        {selected && claimStep === 1 && <Stack spacing={2}>
          <Chip label={selected.channel} size="small" sx={{ alignSelf: 'flex-start', bgcolor: 'action.hover' }} />
          <Typography variant="h5" fontWeight={720}>{selected.title}</Typography>
          <Typography color="text.secondary">{selected.description}</Typography>
          <Button variant="outlined" startIcon={<YouTube />} endIcon={<Launch sx={{ fontSize: 15 }} />} component="a" href={selected.video} target="_blank" rel="noreferrer" sx={{ alignSelf: 'flex-start' }}>Open the video</Button>
          <Divider />
          <Box><Typography variant="body2" fontWeight={700}>Write your comment</Typography><Typography variant="caption" color="text.secondary">A comment is required. Say it in your own words; nothing is prefilled.</Typography></Box>
          <TextField label="Your comment" placeholder="Write your comment in your own words…" value={commentText} onChange={e => setCommentText(e.target.value)} multiline minRows={4} maxRows={6} required fullWidth helperText="Required. A unique claim sentence is appended when you copy." />
          <Paper variant="outlined" sx={{ p: 2, borderRadius: 2, bgcolor: 'action.hover' }}><Typography variant="caption" color="text.secondary">Your claim sentence</Typography><Stack alignItems="flex-start" spacing={1.5} sx={{ mt: .75 }}><Typography sx={{ fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace', fontWeight: 720, overflowWrap: 'anywhere' }}>{claimCode}</Typography><Button size="small" variant="contained" startIcon={<ContentCopy />} sx={{ alignSelf: 'flex-start', whiteSpace: 'nowrap' }} onClick={() => copyComment(true)} disabled={!commentText.trim()}>Copy comment + continue</Button></Stack></Paper>
          <Typography variant="caption" color="text.secondary">This generated sentence is only a claim code, not a crypto wallet key or recovery phrase. Never use it to secure a wallet.</Typography>
        </Stack>}
        {selected && claimStep === 2 && <Stack spacing={2}>
          <Alert severity="info">Paste the copied text as a comment on <b>{selected.channel}</b>’s YouTube video. Then return here and click <b>Check my comment</b>.</Alert>
          <Button variant="outlined" startIcon={<YouTube />} endIcon={<Launch sx={{ fontSize: 15 }} />} component="a" href={selected.video} target="_blank" rel="noreferrer" sx={{ alignSelf: 'flex-start' }}>Open the video</Button>
          <Typography variant="body2" color="text.secondary">We’ll look through recent public comments for your sentence. YouTube may limit or change comment access, so verification can sometimes fail.</Typography>
          <Paper variant="outlined" sx={{ p: 2, borderRadius: 2, bgcolor: 'action.hover' }}><Typography variant="caption" color="text.secondary">Sentence to find</Typography><Stack direction="column" alignItems="flex-start" spacing={1.5} sx={{ mt: .75 }}><Typography sx={{ minWidth: 0, fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace', fontWeight: 720, overflowWrap: 'anywhere' }}>{claimCode}</Typography><Button size="small" startIcon={<ContentCopy />} sx={{ alignSelf: 'flex-start', px: 0 }} onClick={() => copyComment(false)} disabled={!commentText.trim()}>Copy again</Button></Stack></Paper>
          {verifyError && <Alert severity="error">{verifyError}</Alert>}
        </Stack>}
        {selected && claimStep === 3 && <Stack spacing={2} alignItems="flex-start" sx={{ py: 1 }}>
          <Avatar sx={{ bgcolor: 'action.hover', color: 'text.primary', width: 48, height: 48 }}><CheckCircle /></Avatar><Typography variant="h5" fontWeight={720}>Claim confirmed</Typography><Typography color="text.secondary">Your resource is ready to open.</Typography>
          {selected.resourceType === 'text'
            ? <Paper variant="outlined" sx={{ p: 2, width: '100%', whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}><Typography variant="body2">{selected.resource}</Typography><Stack direction="row" spacing={1} sx={{ mt: 1, flexWrap: 'wrap' }}><Button size="small" startIcon={<ContentCopy />} onClick={copyResourceText}>Copy text</Button><Button size="small" startIcon={<Download />} onClick={downloadResourceText}>Save as .txt</Button></Stack></Paper>
            : <Stack direction="row" spacing={1} sx={{ flexWrap: 'wrap' }}><Button variant="contained" endIcon={<ArrowForward />} component="a" href={selected.resource} target="_blank" rel="noreferrer">Open resource</Button><Button startIcon={<ContentCopy />} onClick={copyResourceLink}>Copy link</Button></Stack>}
          <TextField label="Email (optional)" type="email" value={email} onChange={e => setEmail(e.target.value)} helperText="For future recovery. This prototype does not send or save your email." size="small" fullWidth sx={{ '& .MuiInputBase-root': { height: 44 }, '& .MuiInputBase-input': { py: 1 }, '& .MuiFormHelperText-root': { mt: 0.5, ml: 0 } }} />
          <Alert severity="info" variant="outlined" sx={{ width: '100%', borderColor: 'divider', bgcolor: 'transparent' }}><Typography variant="caption">Nothing is stored on the server. Your unlocked link or text lives only in this browser tab's session storage, so copy or save it now if you need it later.</Typography></Alert>
        </Stack>}
      </DialogContent>
      {(claimStep === 2 || claimStep === 3) && <DialogActions sx={{ p: 2 }}>
        {claimStep === 2 && <Button variant="contained" startIcon={<CheckCircle />} disabled={verifyBusy} onClick={verifyComment}>{verifyBusy ? 'Checking…' : 'Check my comment'}</Button>}
        {claimStep === 3 && <Button onClick={closeClaim}>Done</Button>}
      </DialogActions>}
    </Dialog>

    <Dialog open={inviteOpen} onClose={() => { if (!inviteBusy) setInviteOpen(false); }} fullWidth maxWidth="sm" PaperProps={{ sx: { borderRadius: 3 } }}>
      <DialogTitle sx={{ fontWeight: 720 }}>Invite a creator</DialogTitle>
      <DialogContent><Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>Create a single-use link bound to the approved email. It expires after seven days. Share it privately with the approved recipient.</Typography>
        {!inviteUrl ? <Stack component="form" id="invite-form" onSubmit={createInvite} spacing={1.75}><TextField label="Approved email address" type="email" value={inviteEmail} onChange={e => setInviteEmail(e.target.value)} required fullWidth />{inviteError && <Alert severity="error">{inviteError}</Alert>}</Stack> : <Stack spacing={1.5}><Alert severity="success">Invitation ready for {inviteEmail}. It can be used once and expires in seven days.</Alert><TextField label="Private invitation link" value={inviteUrl} fullWidth InputProps={{ readOnly: true }} /><Button variant="outlined" startIcon={<ContentCopy />} onClick={copyInvite}>Copy invitation link</Button><Typography variant="caption" color="text.secondary">Share privately with the approved person. Anyone holding the link still needs access to the invited email account.</Typography></Stack>}
      </DialogContent><DialogActions sx={{ p: 2.5 }}><Button onClick={() => setInviteOpen(false)}>Close</Button>{!inviteUrl && <Button type="submit" form="invite-form" variant="contained" disabled={inviteBusy || !inviteEmail.trim()}>{inviteBusy ? 'Creating…' : 'Create invitation'}</Button>}</DialogActions>
    </Dialog>

    <Dialog open={newOpen} onClose={() => { if (!campaignSaveBusy) setNewOpen(false); }} fullWidth maxWidth="sm" PaperProps={{ sx: { borderRadius: 3 } }}>
      <DialogTitle sx={{ fontWeight: 720 }}>{editingCampaignId ? 'Edit campaign' : 'Create a campaign'}</DialogTitle>
      <DialogContent><Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>Share a useful resource with people who watch your video.</Typography><Stack spacing={1.75}>
        <TextField label="Campaign name" value={newCampaign.title} onChange={e => setNewCampaign({ ...newCampaign, title: e.target.value })} fullWidth />
        <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1} alignItems={{ sm: 'flex-start' }}>
          <TextField label="YouTube video or Short URL" placeholder="https://youtube.com/shorts/…" value={newCampaign.video} onChange={e => { setNewCampaign({ ...newCampaign, video: e.target.value, handle: '' }); setVideoInfo(null); setVideoInfoError(''); }} fullWidth />
          <Button variant="outlined" onClick={fetchVideoInfo} disabled={videoInfoBusy || !newCampaign.video.trim()} sx={{ minWidth: 150, width: { sm: 'auto' }, height: 56, minHeight: 56, whiteSpace: 'nowrap' }}>{videoInfoBusy ? 'Fetching…' : 'Fetch video info'}</Button>
        </Stack>
        {videoInfoError && <Alert severity="error">{videoInfoError}</Alert>}
        {videoInfo && <Paper variant="outlined" sx={{ p: 1.5, display: 'flex', alignItems: 'center', gap: 1.5 }}>
          {videoInfo.thumbnailUrl && <Box component="img" src={videoInfo.thumbnailUrl} alt="YouTube video thumbnail" sx={{ width: 112, aspectRatio: '16 / 9', objectFit: 'cover', borderRadius: 1 }} />}
          <Box><Typography variant="body2" fontWeight={700}>{videoInfo.title}</Typography><Typography variant="caption" color="text.secondary">{videoInfo.channel}{videoInfo.handle ? ` · ${videoInfo.handle}` : ''}</Typography></Box>
        </Paper>}
        <TextField label="Channel name" placeholder="Your YouTube channel" value={newCampaign.channel} onChange={e => setNewCampaign({ ...newCampaign, channel: e.target.value })} fullWidth />
        <TextField select label="Resource type" value={newCampaign.resourceType} onChange={e => setNewCampaign({ ...newCampaign, resourceType: e.target.value, resource: '' })} fullWidth><MenuItem value="link">Link</MenuItem><MenuItem value="text">Text</MenuItem></TextField>
        {newCampaign.resourceType === 'link'
          ? <TextField label="Resource link" placeholder="https://…" value={newCampaign.resource} onChange={e => setNewCampaign({ ...newCampaign, resource: e.target.value })} helperText="Shown only after a viewer’s comment is verified." fullWidth />
          : <TextField label="Resource text" placeholder="Write the text viewers can unlock…" value={newCampaign.resource} onChange={e => setNewCampaign({ ...newCampaign, resource: e.target.value })} multiline minRows={4} inputProps={{ maxLength: 5000 }} helperText={`${newCampaign.resource.length}/5000 characters. Copied or saved from the viewer’s browser after verification.`} fullWidth />}
        <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1.5}><TextField label="Claim limit (optional)" type="number" value={newCampaign.limit} onChange={e => setNewCampaign({ ...newCampaign, limit: e.target.value })} fullWidth /><TextField label="End date (optional)" type="date" InputLabelProps={{ shrink: true }} value={newCampaign.ends} onChange={e => setNewCampaign({ ...newCampaign, ends: e.target.value })} fullWidth /></Stack>
        <Alert severity="info">Choose a link or plain text to reveal after verification. Nothing is uploaded or stored as a file.</Alert>
      </Stack></DialogContent>
      <DialogActions sx={{ p: 2.5 }}><Button disabled={campaignSaveBusy} onClick={() => { setNewOpen(false); setEditingCampaignId(null); }}>Cancel</Button><Button variant="contained" onClick={saveCampaign} disabled={campaignSaveBusy || !newCampaign.title.trim() || !newCampaign.channel.trim() || !newCampaign.video.trim() || !newCampaign.resource.trim()}>{campaignSaveBusy ? 'Saving…' : editingCampaignId ? 'Save changes' : 'Create campaign'}</Button></DialogActions>
    </Dialog>

    {snack && <Box role="status" sx={{ position: 'fixed', bottom: 24, left: '50%', transform: 'translateX(-50%)', zIndex: 2000, bgcolor: 'text.primary', color: 'background.paper', px: 2.25, py: 1.2, borderRadius: 2, boxShadow: 4, fontSize: 13 }}>{snack}</Box>}
  </ThemeProvider>;
}

function PageHeading({ eyebrow, title, description, action }) {
  return <Stack direction={{ xs: 'column', sm: 'row' }} justifyContent="space-between" alignItems={{ xs: 'flex-start', sm: 'end' }} spacing={2} sx={{ pt: { xs: 4, md: 5 }, pb: 3 }}>
    <Box><Typography variant="overline" color="primary.main" sx={{ fontWeight: 750, letterSpacing: '.11em' }}>{eyebrow}</Typography><Typography variant="h2" sx={{ fontSize: { xs: 34, md: 42 }, mt: .2 }}>{title}</Typography><Typography color="text.secondary" sx={{ mt: .7 }}>{description}</Typography></Box>{action}
  </Stack>;
}

function Metric({ label, value, note, icon }) {
  return <Paper variant="outlined" sx={{ p: 2.25, borderRadius: 2.5 }}><Stack direction="row" justifyContent="space-between" alignItems="flex-start"><Box><Typography variant="caption" color="text.secondary">{label}</Typography><Typography variant="h4" sx={{ mt: .7, fontSize: 28 }}>{value}</Typography><Typography variant="caption" color="text.secondary">{note}</Typography></Box><Avatar sx={{ width: 35, height: 35, bgcolor: 'action.hover', color: 'primary.main' }}>{icon}</Avatar></Stack></Paper>;
}

function DropCard({ campaign, onOpen, progress, claimed }) {
  const videoId = youtubeVideoId(campaign.video);
  return <Card variant="outlined" sx={{ borderRadius: 2.5, height: '100%', display: 'flex', flexDirection: 'column', overflow: 'hidden', transition: 'border-color .18s, transform .18s', '&:hover': { borderColor: 'primary.main', transform: 'translateY(-2px)' } }}>
    <Box sx={{ position: 'relative', width: '100%', aspectRatio: '16 / 9', display: 'grid', placeItems: 'center', overflow: 'hidden', bgcolor: 'action.hover', borderBottom: 1, borderColor: 'divider' }}>
      <YouTube sx={{ color: 'text.secondary', fontSize: 32 }} />
      {videoId && <Box component="img" src={`https://i.ytimg.com/vi/${videoId}/hqdefault.jpg`} alt={`${campaign.title} video thumbnail`} loading="lazy" onError={e => { e.currentTarget.style.display = 'none'; }} sx={{ position: 'absolute', inset: 0, width: '100%', height: '100%', objectFit: 'cover' }} />}
    </Box>
    <CardContent sx={{ p: 2.25, flexGrow: 1, display: 'flex', flexDirection: 'column' }}>
      <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 2, minHeight: 28 }}><Chip size="small" label={campaign.category} variant="outlined" sx={{ borderColor: 'divider', fontSize: 11 }} /><Typography variant="caption" color="text.secondary">{claimed ? 'Claimed' : campaign.status}</Typography></Stack>
      <Stack direction="row" spacing={1.25} alignItems="center" sx={{ mb: 1.5, minHeight: 44 }}><Avatar sx={{ width: 37, height: 37, bgcolor: 'action.hover', color: 'text.secondary', fontWeight: 700, fontSize: 12 }}>{campaign.initials}</Avatar><Box sx={{ minWidth: 0 }}><Typography variant="body2" fontWeight={700}>{campaign.channel}</Typography>{campaign.handle && <Typography variant="caption" color="text.secondary">{campaign.handle}</Typography>}</Box></Stack>
      <Typography variant="h6" sx={{ fontSize: 18, lineHeight: 1.35, fontWeight: 700, minHeight: 49, display: '-webkit-box', WebkitBoxOrient: 'vertical', WebkitLineClamp: 2, overflow: 'hidden' }}>{campaign.title}</Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mt: .9, lineHeight: 1.6, minHeight: 45, display: '-webkit-box', WebkitBoxOrient: 'vertical', WebkitLineClamp: 2, overflow: 'hidden' }}>{campaign.description}</Typography>
      <Box sx={{ mt: 'auto', pt: 1.5 }}>
        <Stack direction="row" justifyContent="space-between" sx={{ minHeight: 20 }}><Typography variant="caption" color="text.secondary">{campaign.claimed} claimed</Typography><Typography variant="caption" color="text.secondary">{campaign.limit ? `${campaign.limit - campaign.claimed} left` : 'No cap'}</Typography></Stack>
        <LinearProgress variant="determinate" value={campaign.limit ? progress : 0} sx={{ mt: .75, height: 4, borderRadius: 5, bgcolor: 'action.hover' }} />
        <Stack direction="row" spacing={.65} alignItems="center" sx={{ mt: 1.5, minHeight: 24, color: 'text.secondary' }}><CalendarMonth sx={{ fontSize: 15 }} /><Typography variant="caption">{campaign.ends === 'No end date' ? 'Available until claimed' : `Ends ${campaign.ends}`}</Typography></Stack>
      </Box>
    </CardContent>
    <Divider />
    <Box sx={{ p: 1.5, display: 'flex', justifyContent: 'flex-end' }}><Button size="small" variant="contained" onClick={onOpen}>Open drop<ArrowForward sx={{ ml: .7, fontSize: 16 }} /></Button></Box>
  </Card>;
}

createRoot(document.getElementById('root')).render(<App />);
