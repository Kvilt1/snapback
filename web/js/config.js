// web/js/config.js

// ── Data Interpreter Logic ───────────────────────────────────────────────────

function toColor(str) {
  let h = 0;
  for (let i = 0; i < str.length; i++) h = str.charCodeAt(i) + ((h << 5) - h) | 0;
  return `hsl(${Math.abs(h) % 360}, 65%, 60%)`;
}

function extractTime(created) {
  return created.split(' ')[1]; // "HH:MM:SS.mmm"
}

function transformMessage(msg, memberMap) {
  const time = extractTime(msg.Created);
  const mediaItem   = msg.media?.[0];
  const mediaFile   = mediaItem?.filename;
  const overlayFile = mediaItem?.overlay;
  let src        = mediaFile ?? null;
  let overlaySrc = overlayFile ?? null;
  let isMp4      = src && src.endsWith('.mp4');

  // Fallback for legacy "media/UUID/" directory references (old splitter output)
  if (src && src.endsWith('/')) {
    const dirName = src.split('/').filter(Boolean).pop();
    src   = src + dirName + '.mp4';
    isMp4 = true;
    // overlaySrc stays null — can't recover overlay UUID without re-running splitter
  }

  const out = {};

  if (msg.From) {
    out.sender = memberMap[msg.From]?.display_name ?? msg.From;
    out.color = toColor(msg.From);
  }

  if (msg.Type === 'snap') {
    if (src) {
      out.media = { src, mediaType: isMp4 ? 'video' : 'image', ...(overlaySrc && { overlay: overlaySrc }) };
    } else {
      out.snapOpened = (msg['Media Type'] || '').toUpperCase() === 'VIDEO' ? 'video' : 'image';
    }
  } else {
    const mt = msg['Media Type'];
    if (mt === 'TEXT') {
      if (msg.Content) out.text = msg.Content;
      else out.unsaved = 'Message';
    } else if (mt === 'NOTE') {
      if (src) {
        out.media = { src, mediaType: 'audio' };
        if (msg.Content) out.text = msg.Content;
      } else {
        out.unsaved = 'Voice Note';
      }
    } else if (mt === 'MEDIA') {
      if (src) {
        out.media = { src, mediaType: isMp4 ? 'video' : 'image', ...(overlaySrc && { overlay: overlaySrc }) };
        if (msg.Content) out.text = msg.Content;
      } else {
        out.unsaved = 'Media';
      }
    } else {
      out.text = `[${mt}]`;
    }
  }

  out.time = time;
  return out;
}

function buildConversation(conv) {
  const isGroup = conv.conversation_type === 'group';

  const memberMap = {};
  for (const m of conv.members) memberMap[m.username] = { display_name: m.display_name };

  const lastMsg = conv.messages[conv.messages.length - 1];
  const isSender = !lastMsg?.From;
  const type = lastMsg?.Type === 'snap' ? 'SNAP' : 'CHAT';
  const timestamp = lastMsg ? extractTime(lastMsg.Created) : '00:00:00.000';
  const messages = conv.messages.map(msg => transformMessage(msg, memberMap));

  const result = { convoType: conv.conversation_type, type, isSender, timestamp, messages };

  if (isGroup) {
    result.name = conv.conversation_title;
    result.bgColor = toColor(conv.id);
  } else {
    result.name = conv.members[0].display_name;
    result.bitmoji = conv.members[0].bitmoji;
  }

  return result;
}

// ── Export ────────────────────────────────────────────────────────────────────

export function buildConfig(json) {
  return {
    headerConfig: {
      date:          json.date,
      conversations: json.stats.conversationCount,
      messages:      json.stats.messageCount,
      media:         json.stats.mediaCount,
    },
    prevDay: json.prev_day ?? null,
    nextDay: json.next_day ?? null,
    conversationConfig: json.conversations.map(buildConversation),
  };
}
