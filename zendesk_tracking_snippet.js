/**
 * Aquera Insights — Direct Tracking Ingest Script
 * ================================================
 * Add this to your Zendesk Help Center theme (document_head.hbs or script.js).
 * 
 * This sends article view events directly to the Aquera Insights backend,
 * bypassing the Zendesk comment mechanism. This allows tracking of external
 * customer views even when the tracking article is restricted to agents-only.
 * 
 * HOW TO INSTALL:
 * 1. Go to Zendesk Admin → Guide → Customize Design → Edit Theme
 * 2. Open document_head.hbs (or script.js)
 * 3. Paste this entire script inside a <script> tag
 * 4. Save and publish the theme
 */

(function() {
  'use strict';

  // ── Configuration ──────────────────────────────────────────────────────────
  var INGEST_URL = 'https://aquera-insights.vercel.app/api/tracking/ingest';
  var INGEST_KEY = 'TgGDFhRb2wIASiM6DzmQjcgh2uG5GwVCpP7yO3ED6qc';
  // ────────────────────────────────────────────────────────────────────────────

  // Extract article ID from URL (e.g. /hc/en-us/articles/12345 or /articles/12345)
  var articleMatch = window.location.pathname.match(/\/articles\/(\d+)/i);
  if (!articleMatch) return;
  var articleId = articleMatch[1];

  // Prevent duplicate fires on the same page load
  if (window.__aquera_tracked) return;
  window.__aquera_tracked = true;

  // Get article title from the page
  var titleEl = document.querySelector('h1.article-title') || 
                document.querySelector('.article-header h1') ||
                document.querySelector('h1');
  var articleTitle = titleEl ? titleEl.textContent.trim() : document.title.replace(' – Aquera', '').trim();

  // Build article URL
  var articleUrl = window.location.href.split('?')[0].split('#')[0];

  // Collect user information from Zendesk JS API
  var userData = {
    user_email: 'anonymous',
    user_name: '',
    email_domain: 'unknown',
    user_role: 'anonymous',
    user_locale: navigator.language || 'en-us',
    user_identifier: '',
    user_group: ''
  };

  function sendEvent(user) {
    var payload = {
      article_id: articleId,
      article_title: articleTitle,
      article_url: articleUrl,
      user_identifier: user.user_identifier,
      user_name: user.user_name,
      user_email: user.user_email,
      email_domain: user.email_domain,
      user_group: user.user_group,
      user_role: user.user_role,
      user_locale: user.user_locale,
      timestamp: new Date().toISOString()
    };

    var body = JSON.stringify(payload);
    
    // Primary: fetch with keepalive (supports custom headers & works across modern browsers)
    try {
      fetch(INGEST_URL + '?key=' + encodeURIComponent(INGEST_KEY), {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Ingest-Key': INGEST_KEY
        },
        body: body,
        keepalive: true
      }).then(function(res) {
        if (res.ok) {
          console.log('[Aquera Insights] View logged:', articleTitle, '(' + user.user_email + ')');
        }
      }).catch(function(err) {
        // Fallback: sendBeacon
        if (navigator.sendBeacon) {
          var url = INGEST_URL + '?key=' + encodeURIComponent(INGEST_KEY);
          navigator.sendBeacon(url, new Blob([body], { type: 'application/json' }));
        }
      });
    } catch(e) {
      if (navigator.sendBeacon) {
        var url = INGEST_URL + '?key=' + encodeURIComponent(INGEST_KEY);
        navigator.sendBeacon(url, new Blob([body], { type: 'application/json' }));
      }
    }
  }

  // Try to get current user from Zendesk HelpCenter API
  if (window.HelpCenter && window.HelpCenter.user && window.HelpCenter.user.email) {
    var u = window.HelpCenter.user;
    userData.user_email = u.email || 'anonymous';
    userData.user_name = u.name || '';
    userData.user_role = u.role || 'end-user';
    userData.email_domain = u.email ? u.email.split('@')[1] || 'unknown' : 'unknown';
    userData.user_identifier = u.id ? String(u.id) : '';
    userData.user_group = u.organizations && u.organizations[0] ? u.organizations[0].name : '';
    sendEvent(userData);
  } else {
    // Fallback: try the Zendesk JS API (async)
    try {
      var req = new XMLHttpRequest();
      req.open('GET', '/api/v2/users/me.json', true);
      req.onload = function() {
        if (req.status === 200) {
          try {
            var resp = JSON.parse(req.responseText);
            var zUser = resp.user || {};
            userData.user_email = zUser.email || 'anonymous';
            userData.user_name = zUser.name || '';
            userData.user_role = zUser.role || 'end-user';
            userData.email_domain = zUser.email ? zUser.email.split('@')[1] || 'unknown' : 'unknown';
            userData.user_identifier = zUser.id ? String(zUser.id) : '';
            if (zUser.organization_id) {
              userData.user_group = String(zUser.organization_id);
            }
          } catch(e) {}
        }
        sendEvent(userData);
      };
      req.onerror = function() {
        // If user is not logged in, still send the event as anonymous
        sendEvent(userData);
      };
      req.send();
    } catch(e) {
      sendEvent(userData);
    }
  }
})();
