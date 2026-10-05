"""Editable draft templates transcribed from CL Paints' supplied form screenshots."""

PHOTO_TERMS = """Photographs and videos can be used for CL Paints’ website, portfolio, marketing and social media only where consent has been given. You may withdraw your consent at any time by emailing info@clpaints.com. Withdrawal of consent will not affect images already published before your request was received.

When withdrawing consent, include the event date, location and names of the people involved to help identify the photograph or video.

No names will be published alongside photographs without further permission. Any request by CL Paints for this permission will be made in writing or by email, never over the phone.

Once images are posted online, CL Paints cannot control third-party sharing. Our privacy policy is available through the link on this page."""

GIVEAWAY_TERMS = """Promoter
This giveaway is organised and promoted by CL Paints (‘the Promoter’).

Eligibility
Entrants must be aged 18 years or over. Only one entry per person is permitted per draw. Employees, contractors and immediate family members of CL Paints are not eligible.

Entry fee and period
Entry is free. There is no limit to the number of entries available for each draw. Entries reopen on 2 March, June, September and December and close at 11:59pm on the day before the next applicable draw month. The opening and closing times displayed for this form govern this draw.

Prize
One winner receives a free two-hour professional face painting booking provided by CL Paints, with an approximate retail value of £90. The prize is non-transferable and cannot be exchanged for cash, credit or an alternative service.

Draw and notification
A winner is selected at random on the first day of the draw month, regardless of the number of entries. The winner is contacted at the email address provided and receives details of redemption and booking arrangements. If the winner does not respond within 14 days, CL Paints reserves the right to select an alternative winner. The winning entry number will be announced on CL Paints’ Facebook and Instagram pages on the draw date.

Redemption
The prize must be redeemed and the booking completed within 12 months of the draw date. Bookings are subject to availability. Travel outside CL Paints’ standard service area of 10 miles from its registered address in Doncaster is payable by the winner and billed at the time of booking. Any booking time beyond the free two hours is payable by the winner at the options given on the booking form. CL Paints reserves the right to decline bookings outside its normal operating areas.

Liability
CL Paints accepts no responsibility for lost, incomplete, delayed or incorrectly submitted entries and reserves the right to amend, suspend or cancel the giveaway where necessary due to circumstances beyond its reasonable control.

Data protection
Personal information is used for giveaway administration, winner notification and related communications and processed in accordance with applicable UK data protection legislation. Marketing emails are optional and require the separate choice below.

Acceptance
Entry constitutes acceptance of these terms. CL Paints reserves the right to refuse entries that do not comply."""

def field(label, kind='text', required=True, options=None):
    result=dict(label=label,type=kind,required=required)
    if options:result['options']=options
    return result

PRESETS = {
    'giveaway': dict(kind='giveaway',title='Quarterly VIP Give-away',description='Enter for a chance to win a free two-hour face painting booking. Entry is free. Your name and email come from your verified account.',terms=GIVEAWAY_TERMS,fields=[
        field('I confirm I am aged 18 or over','checkbox'),
        field('I am not an employee, contractor or immediate family member of CL Paints','checkbox'),
        field('I would like marketing updates and news from CL Paints by email','select',True,['No','Yes']),
    ]),
    'photo': dict(kind='photo',title='Photography consent',description='Share your event photos or videos with CL Paints. Name each participant and confirm permission for each person. Submissions are stored privately for review.',terms=PHOTO_TERMS,fields=[
        field('Date of event','date'),field('Venue'),field('Activity','select',True,['Face Painting','Body Painting','Other']),
        field('I am at least 18 years old or the legal parent/guardian of the minor participant','checkbox'),
        field('I understand CL Paints cannot control third-party sharing once images are posted online','checkbox'),
        field('Signature — type your full name'),
    ]),
    'halloween': dict(kind='booking',title='Halloween promotion',description='Tell us about your Halloween design. Your client details, address, event date and time are collected in the booking form below.',terms='',fields=[
        field('Face / body paint requested','checkbox',False),field('Prosthetics requested','checkbox',False),
        field('Explain your design','textarea'),
        field('Link to your design ideas (optional)','text',False),
    ]),
}
