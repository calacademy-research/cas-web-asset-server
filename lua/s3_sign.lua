-- AWS SigV4 signing for S3-compatible endpoints (MinIO).
-- Runs in /_s3_internal/<bucket>/<key> and signs the upstream request.
--
-- Requires: openresty/lua-resty-string (resty.string + resty.sha256)
--
-- Env vars:
--   S3_ACCESS_KEY
--   S3_SECRET_KEY
--   S3_REGION (default: us-east-1)

local resty_string = require "resty.string"
local resty_sha256 = require "resty.sha256"
local bit = require "bit"

local function getenv(name)
    local v = os.getenv(name)
    if v == nil or v == "" then
        return nil
    end
    return v
end

local access_key = getenv("S3_ACCESS_KEY")
local secret_key = getenv("S3_SECRET_KEY")
local region     = getenv("S3_REGION") or "us-east-1"

if not access_key or not secret_key then
    ngx.log(ngx.ERR, "S3 signing is enabled but S3_ACCESS_KEY / S3_SECRET_KEY is not set")
    return ngx.exit(500)
end

-- SHA256 digest, returning raw bytes
local function sha256_bin(msg)
    local sha = resty_sha256:new()
    sha:update(msg)
    return sha:final() -- raw bytes
end

local function sha256_hex(msg)
    return resty_string.to_hex(sha256_bin(msg))
end

-- XOR two byte-strings of the same length
local function xor_bytes(a, b)
    local out = {}
    for i = 1, #a do
        out[i] = string.char(bit.bxor(a:byte(i), b:byte(i)))
    end
    return table.concat(out)
end

-- HMAC-SHA256 implemented using sha256_bin (RFC 2104)
local function hmac_sha256(key, msg)
    local block_size = 64 -- SHA256 block size

    if #key > block_size then
        key = sha256_bin(key)
    end
    if #key < block_size then
        key = key .. string.rep("\0", block_size - #key)
    end

    local o_key_pad = xor_bytes(key, string.rep(string.char(0x5c), block_size))
    local i_key_pad = xor_bytes(key, string.rep(string.char(0x36), block_size))

    local inner = sha256_bin(i_key_pad .. msg)
    return sha256_bin(o_key_pad .. inner) -- raw bytes
end

local function get_amz_datetime()
    -- ISO8601 basic format: YYYYMMDD'T'HHMMSS'Z'
    return os.date("!%Y%m%dT%H%M%SZ")
end

local method = ngx.req.get_method()
if method ~= "GET" and method ~= "HEAD" then
    ngx.log(ngx.WARN, "Unexpected method for S3 signing: ", method)
end

-- Set by nginx.conf (your internal location)
local bucket = ngx.var.s3_bucket or ""
local key    = ngx.var.s3_key or ""

-- Path-style: /<bucket>/<key>
local canonical_uri = "/" .. bucket .. "/" .. key
local canonical_querystring = ""

local amz_date   = get_amz_datetime()
local date_stamp = string.sub(amz_date, 1, 8)

-- Host must match upstream host:port used by proxy_pass
local host = ngx.var.s3_host or ""
local port = ngx.var.s3_port or ""

local host_header = host
if port ~= "" and port ~= "80" and port ~= "443" then
    host_header = host .. ":" .. port
end

ngx.req.set_header("Host", host_header)
ngx.req.set_header("x-amz-date", amz_date)
ngx.req.set_header("x-amz-content-sha256", "UNSIGNED-PAYLOAD")

local canonical_headers =
      "host:" .. host_header .. "\n" ..
      "x-amz-content-sha256:UNSIGNED-PAYLOAD\n" ..
      "x-amz-date:" .. amz_date .. "\n"

local signed_headers = "host;x-amz-content-sha256;x-amz-date"
local payload_hash   = "UNSIGNED-PAYLOAD"

local canonical_request = table.concat({
    method,
    canonical_uri,
    canonical_querystring,
    canonical_headers,
    signed_headers,
    payload_hash
}, "\n")

local algorithm        = "AWS4-HMAC-SHA256"
local credential_scope = date_stamp .. "/" .. region .. "/s3/aws4_request"

local string_to_sign = table.concat({
    algorithm,
    amz_date,
    credential_scope,
    sha256_hex(canonical_request)
}, "\n")

-- Derive signing key
local k_date    = hmac_sha256("AWS4" .. secret_key, date_stamp)
local k_region  = hmac_sha256(k_date, region)
local k_service = hmac_sha256(k_region, "s3")
local k_signing = hmac_sha256(k_service, "aws4_request")

local signature = resty_string.to_hex(hmac_sha256(k_signing, string_to_sign))

local authorization_header = algorithm .. " " ..
    "Credential=" .. access_key .. "/" .. credential_scope .. ", " ..
    "SignedHeaders=" .. signed_headers .. ", " ..
    "Signature=" .. signature

ngx.req.set_header("Authorization", authorization_header)