"""Explicit portal areas for PIN staff. Unclassified admin routes remain owner-only."""
import json

# key, label, landing endpoint, scope shown to the administrator
AREAS = (
    ('pos','Point of sale','pos_home','Sell items, link waivers, view sale history and hold baskets.'),
    ('pos_manager','Till management','pos_reconcile','Also change prices, manage items, refund sales and reconcile the till.'),
    ('bookings','Bookings','admin_bookings','View and manage bookings, requests, messages and booking access.'),
    ('calendar','Availability calendar','admin_calendar','View and manage availability and shared calendar entries.'),
    ('events','Public events & QR codes','admin_events','Create and manage public events and their waiver QR codes.'),
    ('moodboards','Event moodboards','admin_moodboard','Manage designs, prices, moodboard orders and fulfilment.'),
    ('event_day','Event-day tools & kiosk','event_day_dashboard','Manage event-day operations and kiosk setup.'),
    ('equipment','Equipment checklist','admin_equipment','Manage equipment items, photos and event category checklists.'),
    ('handovers','Daily handovers & cash-up','admin_daily_handovers','View and record handovers and booking cash-ups.'),
    ('clients','Client accounts','admin_clients','View/edit client accounts and profiles, including their linked booking, payment and message history.'),
    ('waivers','Waivers, participants & photos','admin_participants','View and manage waivers, participants and their private photos.'),
    ('loyalty','Loyalty visits & check-in','loyalty.check_in','View loyalty records, check-in tools and correct awards.'),
    ('rewards','Referral rewards','admin_rewards','Manage referral codes and reward redemptions.'),
    ('forms','Forms & offers','forms_offers','Build forms, manage entries, files, offers and giveaway draws.'),
    ('rota','Staff rota','connecteam_rota','View the staff rota.'),
    ('timesheets','Clocking & timesheets','admin_staff_timesheets','Manage staff clocking records and timesheets.'),
    ('staff_reports','Staff reports','staff_reports','Create and manage staff reports and their attachments.'),
    ('communications','Messages, enquiries & email history','communications_messages','Read and manage correspondence and outgoing email records.'),
    ('email_templates','Email templates & layout','communications_templates','Edit email content and layout; excludes server configuration.'),
    ('marketing','Email campaigns','marketing_dashboard','Create and manage marketing campaigns.'),
    ('payments','Payments & invoices','payments_overview','Manage payments, deposits, invoices and online payment checks.'),
    ('cash','Cash movements','admin_cash_movements','View and record cash movements and till denominations.'),
    ('reports','Business reports & targets','admin_reports','View/export business reports and update targets.'),
    ('qr_analytics','QR analytics','admin_qr_analytics','View analytics and organise QR codes and signs.'),
    ('photos','Photo library & stories','admin_photo_library','Manage public images and event stories.'),
    ('website','Website builder & pages','admin_website_builder','Edit and publish website content.'),
    ('gallery','Studio gallery moderation','studio_gallery_admin','Review and moderate client gallery designs.'),
    ('creates','CL Creates','creates_admin','Manage CL Creates orders, products, payments and fulfilment.'),
    ('imports','Record imports','admin_record_imports','Import client and booking records.'),
    ('booking_terms','Booking terms','admin_booking_terms','Edit booking terms and conditions.'),
    ('notifications','Activity & notifications','admin_notification_centre','View portal activity and notifications.'),
)
KEYS = frozenset(row[0] for row in AREAS)
MODULE_AREAS = {
    **dict.fromkeys(('booking_access','booking_deletion','booking_edit','booking_lifecycle','booking_messages','booking_requests'),'bookings'),
    'booking_import':'imports','booking_cashup':'handovers','cashup_invoice_payments':'handovers',
    'booking_terms':'booking_terms','business_promotions':'forms','cash_journal':'cash',
    'email_media':'email_templates','email_layout':'email_templates','email_presets':'email_templates',
    'admin_client_profiles':'clients','admin_client_timeline':'clients','client_portal':'clients',
    'event_day':'event_day','kiosk':'event_day','participant_photos':'waivers',
    'equipment_checklist':'equipment',
    'loyalty':'loyalty','rewards':'rewards','rewards_transfer':'rewards',
    'connecteam_rota':'rota','staff_timesheets':'timesheets','staff_reports':'staff_reports',
    **dict.fromkeys(('form_workflows','giveaway_draw','giveaway_import','giveaway_removal','native_forms','native_form_records'),'forms'),
    **dict.fromkeys(('outgoing_emails','outgoing_email_import','website_enquiries'),'communications'),
    'marketing':'marketing','historical_finances':'reports','reports':'reports','report_targets':'reports',
    'invoice_documents':'payments','sumup_checkout':'payments','sumup_invoices':'payments','sumup_invoice_sync':'payments',
    'moodboard_export':'moodboards','moodboard_payments':'moodboards','daily_handovers':'handovers',
    'qr_analytics':'qr_analytics','record_imports':'imports','studio_community':'gallery',
    'website_pages':'website','website_reports':'website',
}
ENDPOINT_AREAS = {}
for area, names in {
    'bookings': 'admin_bookings admin_manage_booking admin_create_booking_events admin_booking_on_behalf',
    'events': 'admin_events admin_event_from_booking admin_create_event admin_rename_event admin_set_event_status admin_archive_event admin_restore_event admin_delete_event admin_event_waiver_qr admin_event_waiver_print',
    'moodboards': 'admin_moodboard_upload admin_moodboard_rename admin_moodboard_delete admin_moodboard admin_moodboard_prices admin_event_moodboard admin_event_moodboard_save admin_event_moodboard_qr admin_event_moodboard_print',
    'waivers': 'admin_waivers admin_participants admin_archived_waivers admin_waiver_detail archive_waiver delete_waiver participant_photo_image',
    'rewards': 'admin_rewards admin_create_referral_code admin_import_referral_codes admin_deactivate_referral_code',
    'calendar': 'admin_calendar delete_availability_block admin_shared_calendar',
    'communications': 'communications_messages communications_history communications_outgoing email_history update_enquiry',
    'email_templates': 'communications_templates email_preview',
    'payments': 'admin_payments payments_overview invoice_document sumup_payment_refresh',
    'loyalty': 'reverse_loyalty',
    'notifications': 'admin_notification_centre admin_phone_notifications',
    'photos': 'admin_photo_upload admin_photo_asset admin_photo_library admin_photo_image admin_website_stories',
    'website': 'admin_website_builder admin_website_report',
    'pos_manager': 'pos_library_save pos_library_batch pos_library_delete pos_library_order pos_variation_colours_save pos_category_save pos_cash_export pos_reconcile pos_refund pos_refund_verify pos_refund_receipt_retry pos_refund_loyalty_review',
    'bookings': 'admin_bookings admin_manage_booking admin_create_booking_events admin_booking_on_behalf',
    'events': 'admin_events admin_event_from_booking admin_create_event admin_rename_event admin_set_event_status admin_archive_event admin_restore_event admin_delete_event admin_event_waiver_qr admin_event_waiver_print',
    'moodboards': 'admin_moodboard_upload admin_moodboard_rename admin_moodboard_delete admin_moodboard admin_moodboard_prices admin_event_moodboard admin_event_moodboard_save admin_event_moodboard_qr admin_event_moodboard_print',
    'rewards': 'admin_rewards admin_create_referral_code admin_import_referral_codes admin_deactivate_referral_code',
    'waivers': 'admin_waivers admin_participants admin_archived_waivers archive_waiver delete_waiver admin_waiver_detail',
}.items():
    ENDPOINT_AREAS.update(dict.fromkeys(names.split(),area))

# These must never be delegated, even when a module contains other allowed routes.
OWNER_ONLY = frozenset(('pos_staff_manage','admin_dashboard','admin_settings','settings_qr_code',
    'backups','rewards.download_database_backup','rewards.import_legacy_data','import_rewards_transfer',
    'admin_global_search','communications_configuration','wedding_followup_settings',
    'google_calendar_connect','google_calendar_callback','google_calendar_disconnect','admin_google_calendar'))
SHARED_PRIVATE = frozenset(('invoice_document','participant_photo_image','native_media','native_field_file','sumup_payment_refresh'))


def permissions(staff):
    if staff.permissions_json is None:
        return {'pos','pos_manager'} if staff.role == 'manager' else {'pos'}
    try:
        values=json.loads(staff.permissions_json)
    except (ValueError,TypeError):
        return set()
    if not isinstance(values,list) or any(not isinstance(value,str) for value in values):
        return set()
    return set(values) & KEYS


def required_area(endpoint, view=None):
    if not endpoint or endpoint in OWNER_ONLY:return None
    if endpoint in ENDPOINT_AREAS:return ENDPOINT_AREAS[endpoint]
    if endpoint.startswith('pos_'):return 'pos'
    if endpoint.startswith('creates_'):return 'creates'
    if endpoint.startswith('communications_'):return 'communications'
    if endpoint.startswith('rewards.'):return 'rewards'
    module=getattr(view,'__module__','').split('.')[-1]
    return MODULE_AREAS.get(module)


def admin_session():
    """For mixed client/admin handlers: staff must have this endpoint's grant."""
    from flask import current_app, request, session
    if session.get('pos_staff_id'):
        access=current_app.extensions.get('pos_access')
        return bool(access and access.allowed(request.endpoint))
    return bool(session.get('admin_authenticated'))


def recorded_actor(fallback):
    from flask import current_app, has_request_context, request, session
    if has_request_context() and session.get('pos_staff_id'):
        access=current_app.extensions.get('pos_access')
        if access and access.allowed(request.endpoint):return access.actor()
    return fallback
