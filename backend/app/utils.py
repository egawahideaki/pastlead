from email.header import decode_header, make_header

def decode_mime(header_value):
    if not header_value:
        return ""
    try:
        # decode_header returns a list of (bytes, encoding) tuples
        decoded_list = decode_header(header_value)
        # make_header converts it back to a proper unicode string
        return str(make_header(decoded_list))
    except Exception:
        return header_value
