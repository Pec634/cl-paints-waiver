# Website search and launch checks

The app now uses the Website address in Admin Settings for canonical URLs, the sitemap, social sharing images and business structured data. Set this to https://www.clpaints.com before launch. Keep contact information and social profile links current in the same settings.

## External actions needed

- Publish the new site and connect clpaints.com with HTTPS. Configure the bare domain to redirect permanently to www.clpaints.com.
- If you own clpaints.uk, configure permanent redirects at its hosting provider to the corresponding .com pages. Do not redirect all pages to the homepage. The app handles /home, /gallery-1 and /about-us once requests reach this server.
- Verify the domain in Google Search Console, submit https://www.clpaints.com/sitemap.xml and inspect the homepage, services and gallery URLs. Search Console is needed to confirm indexing and search performance.
- Update Google Business Profile and directory listings with the same business name, operating area, website, current contact details and current prices. Keep the London registered office distinct from the Doncaster service area.
- Check the published site in PageSpeed Insights on mobile and desktop. Local layout tests do not establish production loading speed or Core Web Vitals.
- For fuller event stories, supply the actual occasion, approved photographs, location and review. Current design stories describe existing photographs without inventing event details.

Private admin and client routes return a noindex header and are excluded from crawler discovery. Authentication remains the access control.
