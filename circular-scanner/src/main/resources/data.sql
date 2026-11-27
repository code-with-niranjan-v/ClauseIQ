INSERT INTO regulatory_source (id, name, regulator, listing_url, allowed_hosts, detail_link_pattern) VALUES
('rbi', 'Reserve Bank of India', 'RBI',
 'https://www.rbi.org.in/Scripts/BS_CircularIndexDisplay.aspx',
 'www.rbi.org.in,rbi.org.in,website.rbi.org.in,rbidocs.rbi.org.in',
 '(?i)(BS_ViewMasCirculardetails|BS_CircularIndexDisplay[.]aspx[?]|NotificationUser|/web/rbi/-/notifications/)'),
('sebi', 'Securities and Exchange Board of India', 'SEBI',
 'https://www.sebi.gov.in/sebiweb/home/HomeAction.do?doListing=yes&sid=1&ssid=7&smid=0',
 'www.sebi.gov.in,sebi.gov.in',
 '(?i)/legal/circulars/[^?]+[.]html'),
('irdai', 'Insurance Regulatory and Development Authority of India', 'IRDAI',
 'https://irdai.gov.in/circulars',
 'irdai.gov.in,www.irdai.gov.in',
 '(?i)(/document-detail[?]|/-/|/circulars/)'),
('dpdp', 'Ministry of Electronics and Information Technology', 'MeitY',
 'https://www.meity.gov.in/cms/wp-json/custom/api/search?s=digital%20personal%20data%20protection',
 'www.meity.gov.in,meity.gov.in,www.indiacode.nic.in,indiacode.nic.in,egazette.gov.in,www.egazette.gov.in,egazette.nic.in,www.egazette.nic.in',
 '(?i)(digital-personal-data-protection|data-protection-framework|/handle/|ViewPDF[.]aspx)')
ON CONFLICT (id) DO NOTHING;

INSERT INTO regulatory_source (id, name, regulator, listing_url, allowed_hosts, detail_link_pattern, enabled)
VALUES ('uploads', 'PDF uploads', 'Manual upload', '', '', '', false)
ON CONFLICT (id) DO NOTHING;

-- Earlier listing URLs stopped working: SEBI removed /legal/circulars.html, and the MeitY page renders
-- its links in the browser, so the scanner reads the public CMS search API that page uses.
UPDATE regulatory_source SET listing_url = 'https://www.sebi.gov.in/sebiweb/home/HomeAction.do?doListing=yes&sid=1&ssid=7&smid=0'
WHERE id = 'sebi' AND listing_url = 'https://www.sebi.gov.in/legal/circulars.html';
UPDATE regulatory_source SET listing_url = 'https://www.meity.gov.in/cms/wp-json/custom/api/search?s=digital%20personal%20data%20protection'
WHERE id = 'dpdp' AND listing_url = 'https://www.meity.gov.in/data-protection-framework';
