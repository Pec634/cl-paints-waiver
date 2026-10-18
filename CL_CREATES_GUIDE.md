# CL Creates

Restart the application to create the four new database tables. Existing booking records and communications are retained.

Startup also upgrades existing CL Creates orders with the acknowledgement field. Older orders are labelled as having no recorded acknowledgement; their customer details, totals and payment records are preserved. The upgrade can safely run on every restart.

## Image library

The **CL Creates image library** supports up to ten uploads at once, previews, captions, public gallery visibility, and permanent deletion. Files must be valid JPEG, PNG or WebP images, at most 5 MB and 20 megapixels each. Uploads are resized, metadata is removed, and image content is validated before storage. Images are stored in the database; include the new image table in backups.

The three supplied example photos are imported from `assets/cl-creates-examples` once on startup. They appear in the public example gallery independently of the products available to order. Deleting an example does not cause it to reappear on restart. The bundled source files remain in the project as import assets and are not publicly served.

Use the library selector in product settings to reuse a photo or replace a product image. Choose **Remove current image** to clear a product photo. Deleting a library image also clears matching product photos; product records and historical orders remain intact. Hidden gallery images can still be used as product photos: the gallery visibility checkbox controls the example gallery only.

Open **CL Creates settings & showcase** in the admin navigation to add named headbands and optional showcase photographs. Active headbands appear at `/cl-creates`; share that URL with customers. Hide products to stop new orders without changing earlier orders.

The public order form is always available, even with no catalogue products. Customers can choose **Custom wording headband**, enter wording and quantity on multiple lines, and submit one combined order. Hiding a catalogue product removes that specific product from the choices; generic custom headbands remain available. The public page describes the contact and delivery fields, wording limits, invoice process and order status stages.

The public form accepts multiple headbands and quantities, with 11 non-space characters and up to two spaces per wording. Default prices are £5 per headband and £6 postage per order, or free collection. Delivery requires a UK address, postcode and mainland confirmation. Review delivery eligibility before invoicing: postcode validation and customer confirmation do not establish that every address is on the mainland.

Orders receive sequential references such as O-000001. Search by reference, name, email or address. Select a reference to open its details in a dialog; the link also works as a standalone page. Attach the HTTPS SumUp invoice URL and reference, then manually record payments verified in SumUp. Invoice links are supported; PDF uploads and automated SumUp reconciliation are not included.

Status choices are Under review, Paid, In production, Shipped and Ready for collection. Full recorded payment is required after Under review. Fulfilment statuses must match postage or collection. Shipped and Ready for collection count as completed in the statistics. Payment statistics show recorded amounts and outstanding balances across all orders. Order counts use current UK calendar day, Monday-start week, month and year.

Automatic confirmation and status emails use the existing portal email delivery service. CL Creates has its own enable switch, subject, body and supported placeholders. Its separate communication history records sent, failed and disabled messages. Send a customer email from order details to follow up or retry failed delivery. Incoming email replies remain in the business mailbox; this is an outbound communication log.

Pricing changes apply only to new orders. Product names, wording, quantities and unit prices are retained on each order. The public form links to the existing privacy policy and records customer acknowledgement; review the policy and customer-facing trading terms for this new product business before launch.

Validation suite: `python -m unittest test_cl_creates`.
