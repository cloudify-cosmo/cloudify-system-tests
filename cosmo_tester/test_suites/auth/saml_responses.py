from datetime import datetime, timedelta


OKTA_SAML_TEMPLATE = '''<?xml version="1.0" encoding="UTF-8"?>
<saml2p:Response Destination="https://192.0.2.4/console/auth/saml/callback" ID="id64321098765432123456789012" IssueInstant="{issue_time}" Version="2.0" xmlns:saml2p="urn:oasis:names:tc:SAML:2.0:protocol" xmlns:xs="http://www.w3.org/2001/XMLSchema">
  <saml2:Issuer Format="urn:oasis:names:tc:SAML:2.0:nameid-format:entity" xmlns:saml2="urn:oasis:names:tc:SAML:2.0:assertion">http://example.samlprovider.local/abc123</saml2:Issuer>
  <ds:Signature xmlns:ds="http://www.w3.org/2000/09/xmldsig#" Id="placeholder"></ds:Signature>
  <saml2:Subject xmlns:saml2="urn:oasis:names:tc:SAML:2.0:assertion">
    <saml2:NameID Format="urn:oasis:names:tc:SAML:1.1:nameid-format:unspecified">{username}</saml2:NameID>
    <saml2:SubjectConfirmation Method="urn:oasis:names:tc:SAML:2.0:cm:bearer">
      <saml2:SubjectConfirmationData NotOnOrAfter="{expire_time}" Recipient="https://192.0.2.4/console/auth/saml/callback"/>
    </saml2:SubjectConfirmation>
  </saml2:Subject>
  <saml2:Assertion xmlns:saml2="urn:oasis:names:tc:SAML:2.0:assertion" ID="id6432109876543212345678901" IssueInstant="{issue_time}" Version="2.0">
    <saml2:Conditions NotBefore="{not_before_time}" NotOnOrAfter="{expire_time}" xmlns:saml2="urn:oasis:names:tc:SAML:2.0:assertion">
      <saml2:AudienceRestriction>
        <saml2:Audience>https://192.0.2.4/console/auth/saml/callback</saml2:Audience>
      </saml2:AudienceRestriction>
    </saml2:Conditions>
    <saml2:AuthnStatement AuthnInstant="{issue_time}" SessionIndex="id123456.7890" xmlns:saml2="urn:oasis:names:tc:SAML:2.0:assertion">
      <saml2:AuthnContext>
        <saml2:AuthnContextClassRef>urn:oasis:names:tc:SAML:2.0:ac:classes:PasswordProtectedTransport</saml2:AuthnContextClassRef>
      </saml2:AuthnContext>
    </saml2:AuthnStatement>
    <saml2:AttributeStatement xmlns:saml2="urn:oasis:names:tc:SAML:2.0:assertion">
      {attributes}
    </saml2:AttributeStatement>
  </saml2:Assertion>
</saml2p:Response>'''  # noqa

AZURE_SAML_TEMPLATE = '''<?xml version="1.0"?>
<samlp:Response xmlns:samlp="urn:oasis:names:tc:SAML:2.0:protocol" ID="_abcdef12-4321-0110-1001-0123456789ab" Version="2.0" IssueInstant="{issue_time}" Destination="https://192.0.2.4/console/auth/saml/callback">
  <Issuer xmlns="urn:oasis:names:tc:SAML:2.0:assertion">https://other.example.local/87654321-1111-2222-3333-4444221100aa/</Issuer>
  <Signature xmlns="http://www.w3.org/2000/09/xmldsig#" Id="placeholder"></Signature>
  <samlp:Status><samlp:StatusCode Value="urn:oasis:names:tc:SAML:2.0:status:Success"/></samlp:Status>
  <Assertion xmlns="urn:oasis:names:tc:SAML:2.0:assertion" ID="_c01dcafe-face-cace-011e-feedadeadc0d" IssueInstant="{issue_time}" Version="2.0">
    <Issuer>https://sts.windows.net/11112222-3333-4444-5555-666677778888/</Issuer>
    <Subject>
      <NameID Format="urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress">{username}</NameID>
      <SubjectConfirmation Method="urn:oasis:names:tc:SAML:2.0:cm:bearer">
        <SubjectConfirmationData NotOnOrAfter="{not_before_time}" Recipient="https://192.0.2.4/console/auth/saml/callback"/>
      </SubjectConfirmation>
    </Subject>
    <Conditions NotBefore="{not_before_time}" NotOnOrAfter="{expire_time}">
      <AudienceRestriction>
        <Audience>https://192.0.2.4/console</Audience>
      </AudienceRestriction>
    </Conditions>
    <AttributeStatement>
      <Attribute Name="http://schemas.microsoft.com/identity/claims/tenantid">
        <AttributeValue>12345678-abcd-dcba-8420-1111bbbbcccc</AttributeValue>
      </Attribute>
      <Attribute Name="http://schemas.microsoft.com/identity/claims/objectidentifier">
        <AttributeValue>aaaabbbb-cccc-dddd-eeee-ffff00002222</AttributeValue>
      </Attribute>
      <Attribute Name="http://schemas.microsoft.com/identity/claims/identityprovider">
        <AttributeValue>https://sts.windows.net/12345678-4321-5678-abcd98761234/</AttributeValue>
      </Attribute>
      <Attribute Name="http://schemas.microsoft.com/claims/authnmethodsreferences">
        <AttributeValue>http://schemas.microsoft.com/ws/2008/06/identity/authenticationmethod/password</AttributeValue>
      </Attribute>
      {attributes}
    </AttributeStatement>
    <AuthnStatement AuthnInstant="{issue_time}" SessionIndex="_10102020-0303-4545-1987-ab21de43f8888">
      <AuthnContext>
        <AuthnContextClassRef>urn:oasis:names:tc:SAML:2.0:ac:classes:Password</AuthnContextClassRef>
      </AuthnContext>
    </AuthnStatement>
  </Assertion>
</samlp:Response>'''  # noqa

OKTA_ATTR_STRING = '<saml2:Attribute Name="{attr_name}" NameFormat="urn:oasis:names:tc:SAML:2.0:attrname-format:unspecified">{attr_value}</saml2:Attribute>'  # noqa
AZURE_ATTR_STRING = '<Attribute Name="{attr_name}">{attr_value}</Attribute>'

OKTA_ATTR_VALUE = '<saml2:AttributeValue xmlns:xs="http://www.w3.org/2001/XMLSchema" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:type="xs:string">{value}</saml2:AttributeValue>'  # noqa
AZURE_ATTR_VALUE = '<AttributeValue>{value}</AttributeValue>'


def _make_xml_datetime(datetime_input, tz=None):
    # Based on the specs here: https://www.w3.org/TR/xmlschema-2/#dateTime
    base = datetime_input.strftime('%Y-%m-%dT%H:%M:%S.')

    # While it's not part of the spec, both azure and okta provide three
    # decimal places of precision, so we'll mirror them
    base += '{:03}'.format(datetime_input.microsecond // 1000)

    # Note that if fractional seconds are present, they must not end in 0
    base = base.rstrip('0.')
    if tz:
        return base + tz
    return base + 'Z'


def _generate_attr(attr_name, attr_value, style):
    if style == 'okta':
        attr_value = OKTA_ATTR_VALUE.format(value=attr_value)
        attr_string = OKTA_ATTR_STRING
    elif style == 'azure':
        attr_value = AZURE_ATTR_VALUE.format(value=attr_value)
        attr_string = AZURE_ATTR_STRING
    else:
        raise RuntimeError(f'Unknown style {style} for generating attr')
    return attr_string.format(attr_name=attr_name, attr_value=attr_value)


def _generate_attributes(username, first_name, last_name, email, groups,
                         style):
    if style == 'okta':
        attr_value_template = OKTA_ATTR_VALUE
        attr_string_template = OKTA_ATTR_STRING
    elif style == 'azure':
        attr_value_template = AZURE_ATTR_VALUE
        attr_string_template = AZURE_ATTR_STRING
    else:
        raise RuntimeError(f'Unknown style {style} for generating attrs')

    attributes = _generate_attr('username', username, style)
    if first_name:
        attributes += _generate_attr('firstname', first_name, style)
    if last_name:
        attributes += _generate_attr('lastname', last_name, style)
    if email:
        attributes += _generate_attr('email', email, style)
    if groups:
        formatted_groups = ''.join(
            attr_value_template.format(value=group)
            for group in groups
        )
        attributes += attr_string_template.format(
            attr_name='groups', attr_value=formatted_groups)
    return attributes


def make_response(username, first_name=None, last_name=None, email=None,
                  groups=None, expired=False, too_soon=False, style='okta'):
    issue_time = datetime.now()
    if expired and too_soon:
        raise RuntimeError("A document can't be expired and not issued yet")
    if expired:
        issue_time -= timedelta(hours=10)
    if too_soon:
        issue_time += timedelta(hours=10)
    not_before_time = issue_time - timedelta(minutes=10)
    expire_time = issue_time + timedelta(minutes=5)

    if style == 'okta':
        template = OKTA_SAML_TEMPLATE
    elif style == 'azure':
        template = AZURE_SAML_TEMPLATE
    else:
        raise RuntimeError(f'Unknown style {style} for making response')

    attributes = _generate_attributes(username, first_name,
                                      last_name, email, groups, style)

    return template.format(
        username=username, attributes=attributes,
        issue_time=_make_xml_datetime(issue_time),
        not_before_time=_make_xml_datetime(not_before_time),
        expire_time=_make_xml_datetime(expire_time),
    )
