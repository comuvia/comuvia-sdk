TEST ONLY. A throwaway CA (test-ca.pem) and a localhost/127.0.0.1 server certificate and key
(test-server.pem, test-server-key.pem), generated for foreglass's offline transport tests.
Nothing outside tests/test_transport.py trusts this CA; the CA's private key was discarded.
