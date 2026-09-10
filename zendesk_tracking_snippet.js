/**
 * Aquera Insights — Direct Tracking Ingest Script for Zendesk script.js
 * ====================================================================
 * In Zendesk Admin → Guide → Customize Design → Edit Theme → script.js:
 * Replace the old "// Analytics" block at the bottom with this snippet.
 */

// ─────────────────────────────────────────────────────────────────────────────
// Aquera Insights Direct Ingest (Vercel)
// ─────────────────────────────────────────────────────────────────────────────
(function() {
  'use strict';

  var INGEST_URL = 'https://aquera-insights.vercel.app/api/tracking/ingest';
  var INGEST_KEY = 'TgGDFhRb2wIASiM6DzmQjcgh2uG5GwVCpP7yO3ED6qc';

  function trackArticle() {
    // Only fire on article pages
    var articleMatch = window.location.pathname.match(/\/articles\/(\d+)/i);
    if (!articleMatch) return;
    var articleId = articleMatch[1];

    if (window.__aquera_tracked) return;
    window.__aquera_tracked = true;

    // Get article title (checks #kb-tracking-data, h1, or document.title)
    var el = document.getElementById("kb-tracking-data");
    var articleTitle = (el ? el.getAttribute("data-article-title") : null);
    if (!articleTitle) {
      var h1 = document.querySelector('h1.article-title') || 
               document.querySelector('.article-header h1') || 
               document.querySelector('h1');
      articleTitle = h1 ? h1.textContent.trim() : document.title.replace(' – Aquera', '').trim();
    }

    var articleUrl = window.location.href.split('?')[0].split('#')[0];

    // Grab user information from Zendesk HelpCenter object
    var u = (window.HelpCenter && window.HelpCenter.user) || {};
    var userEmail = u.email || 'anonymous';
    var userName = u.name || '';
    var userRole = u.role || 'anonymous';
    var userOrg = (u.organizations && u.organizations[0] && u.organizations[0].name) || '';
    var emailDomain = userEmail.indexOf('@') !== -1 ? userEmail.split('@')[1].toLowerCase().trim() : 'unknown';

    var payload = {
      article_id: articleId,
      article_title: articleTitle,
      article_url: articleUrl,
      user_identifier: u.id ? String(u.id) : (u.identifier || ''),
      user_name: userName,
      user_email: userEmail,
      email_domain: emailDomain,
      user_group: userOrg,
      user_role: userRole,
      user_locale: u.locale || navigator.language || 'en-us',
      timestamp: new Date().toISOString()
    };

    var body = JSON.stringify(payload);

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
          console.log('✅ [Aquera Insights] Ingested:', articleTitle, 'by', userEmail);
        }
      }).catch(function() {
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

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', trackArticle);
  } else {
    trackArticle();
  }
})();
