from flask import render_template, Response, url_for, redirect, request
from xml.sax.saxutils import escape


def register(app):
    def public_url(endpoint, **values):
        context = {}
        app.update_template_context(context)
        origin = (context['business_settings']['website'] or 'https://my.clpaints.com/').rstrip('/')
        return origin + url_for(endpoint, **values)

    @app.context_processor
    def website_seo_context():
        return {'website_public_url': public_url, 'website_photo_alts': {
            1: 'CL Paints event setup with colourful palettes, brushes and a face painting design board',
            2: 'Football cheek painting with green and black brush strokes',
            3: 'Orange and yellow mermaid face painting with flowers and glitter',
            4: 'Orange tiger face painting with black stripes and glitter',
            5: 'Pastel rainbow face painting with white stars and pink glitter',
            6: 'Pastel butterfly face painting with a fairy silhouette and blue gems',
        }}

    for old_path, destination in [('/home', 'home'), ('/home/', 'home'), ('/gallery-1', 'gallery'), ('/gallery-1/', 'gallery'), ('/about-us', 'about'), ('/about-us/', 'about')]:
        app.add_url_rule(old_path, 'legacy_website_' + old_path.replace('/', '_'),
                         lambda destination=destination: redirect(url_for('website_' + destination), code=301))

    @app.after_request
    def private_pages_noindex(response):
        if request.path.startswith(('/admin', '/client')):
            response.headers['X-Robots-Tag'] = 'noindex, nofollow'
        return response

    @app.get('/robots.txt')
    def website_robots():
        return Response('User-agent: *\nAllow: /\nDisallow: /admin/\nDisallow: /client/\nSitemap: ' + public_url('website_sitemap') + '\n', mimetype='text/plain')
    pages = {
        'home': ('/', 'Face Painting in Doncaster & South Yorkshire | CL Paints', 'Colourful face painting for birthday parties, festivals and events in Doncaster and South Yorkshire. Explore designs and enquire with CL Paints.'),
        'services': ('/services', 'Face Painting Services & Prices | CL Paints', 'Explore private party and public event face painting with CL Paints. View current pricing, discuss arrangements and request your event.'),
        'about': ('/about', 'Meet the Team | CL Paints Doncaster', 'Meet Chloe and Deklan, the team behind CL Paints, bringing creativity and colourful face painting to events in Doncaster and surrounding areas.'),
        'gallery': ('/gallery', 'Face Painting Gallery | CL Paints', 'Explore colourful face painting designs by CL Paints for birthday parties, festivals and events in Doncaster and surrounding areas.'),
        'contact': ('/contact', 'Contact & Booking Enquiries | CL Paints', 'Contact CL Paints about face painting for your event. Check your preferred date or send a booking request through our client portal.'),
        'studio': ('/face-paint-studio', 'Face Paint Studio | CL Paints', 'Try face painting online with our creative studio. Choose a face, explore colours and create your own design.'),
    }
    def show(page):
        return render_template('website/studio.html' if page=='studio' else 'website/page.html', page=page, seo_title=pages[page][1], seo_description=pages[page][2])
    for page, (path, _, _) in pages.items():
        app.add_url_rule(path, 'website_' + page, lambda page=page: show(page))
    @app.get('/sitemap.xml')
    def website_sitemap():
        urls = ''.join('<url><loc>' + escape(public_url('website_' + page)) + '</loc></url>' for page in pages)
        return Response('<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' + urls + '</urlset>', mimetype='application/xml')
