Object.defineProperty(exports, Symbol.toStringTag, { value: "Module" });
//#region \0rolldown/runtime.js
var __create = Object.create;
var __defProp = Object.defineProperty;
var __getOwnPropDesc = Object.getOwnPropertyDescriptor;
var __getOwnPropNames = Object.getOwnPropertyNames;
var __getProtoOf = Object.getPrototypeOf;
var __hasOwnProp = Object.prototype.hasOwnProperty;
var __copyProps = (to, from, except, desc) => {
	if (from && typeof from === "object" || typeof from === "function") for (var keys = __getOwnPropNames(from), i = 0, n = keys.length, key; i < n; i++) {
		key = keys[i];
		if (!__hasOwnProp.call(to, key) && key !== except) __defProp(to, key, {
			get: ((k) => from[k]).bind(null, key),
			enumerable: !(desc = __getOwnPropDesc(from, key)) || desc.enumerable
		});
	}
	return to;
};
var __toESM = (mod, isNodeMode, target) => (target = mod != null ? __create(__getProtoOf(mod)) : {}, __copyProps(isNodeMode || !mod || !mod.__esModule || !__hasOwnProp.call(mod, "default") ? __defProp(target, "default", {
	value: mod,
	enumerable: true
}) : target, mod));
//#endregion
let node_assert = require("node:assert");
node_assert = __toESM(node_assert, 1);
let node_util = require("node:util");
let node_crypto = require("node:crypto");
node_crypto = __toESM(node_crypto, 1);
let node_net = require("node:net");
node_net = __toESM(node_net, 1);
let node_tls = require("node:tls");
node_tls = __toESM(node_tls, 1);
let node_events = require("node:events");
//#region src/ber/Ber.ts
const Ber = {
	EOC: 0,
	Boolean: 1,
	Integer: 2,
	BitString: 3,
	OctetString: 4,
	Null: 5,
	OID: 6,
	ObjectDescriptor: 7,
	External: 8,
	Real: 9,
	Enumeration: 10,
	PDV: 11,
	Utf8String: 12,
	RelativeOID: 13,
	Sequence: 16,
	Set: 17,
	NumericString: 18,
	PrintableString: 19,
	T61String: 20,
	VideotexString: 21,
	IA5String: 22,
	UTCTime: 23,
	GeneralizedTime: 24,
	GraphicString: 25,
	VisibleString: 26,
	GeneralString: 28,
	UniversalString: 29,
	CharacterString: 30,
	BMPString: 31,
	Constructor: 32,
	Context: 128
};
//#endregion
//#region src/ber/InvalidAsn1Error.ts
var InvalidAsn1Error = class extends Error {
	constructor(message) {
		super(message);
		this.name = "InvalidAsn1Error";
	}
};
//#endregion
//#region src/ber/BerReader.ts
var BerReader = class {
	size;
	currentLength = 0;
	currentOffset = 0;
	buffer;
	constructor(data) {
		if (!Buffer.isBuffer(data)) throw new TypeError("data must be a Buffer");
		this.buffer = data;
		this.size = data.length;
	}
	get length() {
		return this.currentLength;
	}
	get offset() {
		return this.currentOffset;
	}
	set offset(value) {
		this.currentOffset = value;
	}
	get remain() {
		return this.size - this.currentOffset;
	}
	get remainingBuffer() {
		return this.buffer.subarray(this.currentOffset);
	}
	setBufferSize(size) {
		this.size = size;
	}
	readByte(peek = false) {
		if (this.size - this.currentOffset < 1) return null;
		const byte = this.buffer.readUInt8(this.currentOffset);
		if (!peek) this.currentOffset += 1;
		return byte;
	}
	peek() {
		return this.readByte(true);
	}
	readLength(startOffset) {
		let offset = startOffset ?? this.currentOffset;
		if (offset >= this.size) return null;
		const lengthByte = this.buffer.readUInt8(offset);
		offset += 1;
		if ((lengthByte & 128) === 128) {
			const numLengthBytes = lengthByte & 127;
			if (numLengthBytes === 0) throw new InvalidAsn1Error("Indefinite length not supported");
			if (numLengthBytes > 4) throw new InvalidAsn1Error("Encoding too long");
			if (this.size - offset < numLengthBytes) return null;
			this.currentLength = 0;
			for (let i = 0; i < numLengthBytes; i++) {
				this.currentLength = (this.currentLength << 8) + this.buffer.readUInt8(offset);
				offset += 1;
			}
		} else this.currentLength = lengthByte;
		return offset;
	}
	readSequence(expectedTag) {
		const tag = this.peek();
		if (tag === null) return null;
		if (expectedTag !== void 0 && expectedTag !== tag) throw new InvalidAsn1Error(`Expected 0x${expectedTag.toString(16)}: got 0x${tag.toString(16)}`);
		const newOffset = this.readLength(this.currentOffset + 1);
		if (newOffset === null) return null;
		this.currentOffset = newOffset;
		return tag;
	}
	readInt() {
		return this.readTag(Ber.Integer);
	}
	readBoolean() {
		const value = this.readTag(Ber.Boolean);
		if (value === null) return null;
		return value !== 0;
	}
	readEnumeration() {
		return this.readTag(Ber.Enumeration);
	}
	readString(tag = Ber.OctetString, asBuffer = false) {
		const currentTag = this.peek();
		if (currentTag === null) return null;
		if (currentTag !== tag) throw new InvalidAsn1Error(`Expected 0x${tag.toString(16)}: got 0x${currentTag.toString(16)}`);
		const newOffset = this.readLength(this.currentOffset + 1);
		if (newOffset === null) return null;
		if (this.currentLength > this.size - newOffset) return null;
		this.currentOffset = newOffset;
		if (this.currentLength === 0) return asBuffer ? Buffer.alloc(0) : "";
		const value = this.buffer.subarray(this.currentOffset, this.currentOffset + this.currentLength);
		this.currentOffset += this.currentLength;
		return asBuffer ? value : value.toString("utf8");
	}
	readOID(tag = Ber.OID) {
		const data = this.readString(tag, true);
		if (data === null) return null;
		const values = [];
		let value = 0;
		for (const byte of data) {
			value = (value << 7) + (byte & 127);
			if ((byte & 128) === 0) {
				values.push(value);
				value = 0;
			}
		}
		const firstValue = values[0] ?? 0;
		return [
			Math.trunc(firstValue / 40),
			firstValue % 40,
			...values.slice(1)
		].join(".");
	}
	readTag(tag) {
		const currentTag = this.peek();
		if (currentTag === null) return null;
		if (currentTag !== tag) throw new InvalidAsn1Error(`Expected 0x${tag.toString(16)}: got 0x${currentTag.toString(16)}`);
		const newOffset = this.readLength(this.currentOffset + 1);
		if (newOffset === null) return null;
		if (this.currentLength > 4) throw new InvalidAsn1Error(`Integer too long: ${this.currentLength}`);
		if (this.currentLength > this.size - newOffset) return null;
		this.currentOffset = newOffset;
		const firstByte = this.buffer.readUInt8(this.currentOffset);
		let value = 0;
		for (let i = 0; i < this.currentLength; i++) {
			value = value << 8 | this.buffer.readUInt8(this.currentOffset);
			this.currentOffset += 1;
		}
		if ((firstByte & 128) === 128 && this.currentLength < 4) value -= 1 << this.currentLength * 8;
		return value >> 0;
	}
};
//#endregion
//#region src/ber/BerWriter.ts
var BerWriter = class {
	data;
	size;
	currentOffset = 0;
	growthFactor;
	sequenceOffsets = [];
	constructor(options = {}) {
		const initialSize = options.size ?? 1024;
		this.growthFactor = options.growthFactor ?? 8;
		this.data = Buffer.alloc(initialSize);
		this.size = initialSize;
	}
	get buffer() {
		if (this.sequenceOffsets.length > 0) throw new InvalidAsn1Error(`${this.sequenceOffsets.length} unended sequence(s)`);
		return this.data.subarray(0, this.currentOffset);
	}
	writeByte(value) {
		this.ensureCapacity(1);
		this.data[this.currentOffset++] = value;
	}
	writeInt(value, tag = Ber.Integer) {
		let intValue = value;
		let byteCount = 4;
		while (((intValue & 4286578688) === 0 || (intValue & 4286578688) === -8388608) && byteCount > 1) {
			byteCount--;
			intValue <<= 8;
		}
		if (byteCount > 4) throw new InvalidAsn1Error("BER integers cannot be > 0xffffffff");
		this.ensureCapacity(2 + byteCount);
		this.data[this.currentOffset++] = tag;
		this.data[this.currentOffset++] = byteCount;
		while (byteCount > 0) {
			byteCount--;
			this.data[this.currentOffset++] = (intValue & 4278190080) >>> 24;
			intValue <<= 8;
		}
	}
	writeNull() {
		this.writeByte(Ber.Null);
		this.writeByte(0);
	}
	writeEnumeration(value, tag = Ber.Enumeration) {
		this.writeInt(value, tag);
	}
	writeBoolean(value, tag = Ber.Boolean) {
		this.ensureCapacity(3);
		this.data[this.currentOffset++] = tag;
		this.data[this.currentOffset++] = 1;
		this.data[this.currentOffset++] = value ? 255 : 0;
	}
	writeString(value, tag = Ber.OctetString) {
		const byteLength = Buffer.byteLength(value);
		this.writeByte(tag);
		this.writeLength(byteLength);
		if (byteLength > 0) {
			this.ensureCapacity(byteLength);
			this.data.write(value, this.currentOffset);
			this.currentOffset += byteLength;
		}
	}
	writeBuffer(value, tag) {
		this.writeByte(tag);
		this.writeLength(value.length);
		this.ensureCapacity(value.length);
		value.copy(this.data, this.currentOffset, 0, value.length);
		this.currentOffset += value.length;
	}
	writeStringArray(values) {
		for (const value of values) this.writeString(value);
	}
	writeOID(value, tag = Ber.OID) {
		if (!/^(\d+\.){3,}\d+$/.test(value)) throw new Error("Argument is not a valid OID string");
		const parts = value.split(".");
		const bytes = [];
		const firstPart = parts[0] ?? "0";
		const secondPart = parts[1] ?? "0";
		bytes.push(Number(firstPart) * 40 + Number(secondPart));
		for (const part of parts.slice(2)) this.encodeOidOctet(bytes, Number(part));
		this.ensureCapacity(2 + bytes.length);
		this.writeByte(tag);
		this.writeLength(bytes.length);
		for (const byte of bytes) this.writeByte(byte);
	}
	writeLength(length) {
		this.ensureCapacity(4);
		if (length <= 127) this.data[this.currentOffset++] = length;
		else if (length <= 255) {
			this.data[this.currentOffset++] = 129;
			this.data[this.currentOffset++] = length;
		} else if (length <= 65535) {
			this.data[this.currentOffset++] = 130;
			this.data[this.currentOffset++] = length >> 8;
			this.data[this.currentOffset++] = length;
		} else if (length <= 16777215) {
			this.data[this.currentOffset++] = 131;
			this.data[this.currentOffset++] = length >> 16;
			this.data[this.currentOffset++] = length >> 8;
			this.data[this.currentOffset++] = length;
		} else throw new InvalidAsn1Error("Length too long (> 4 bytes)");
	}
	startSequence(tag = Ber.Sequence | Ber.Constructor) {
		this.writeByte(tag);
		this.sequenceOffsets.push(this.currentOffset);
		this.ensureCapacity(3);
		this.currentOffset += 3;
	}
	endSequence() {
		const sequenceStart = this.sequenceOffsets.pop();
		if (sequenceStart === void 0) throw new InvalidAsn1Error("No sequence to end");
		const contentStart = sequenceStart + 3;
		const contentLength = this.currentOffset - contentStart;
		if (contentLength <= 127) {
			this.shiftContent(contentStart, contentLength, -2);
			this.data[sequenceStart] = contentLength;
		} else if (contentLength <= 255) {
			this.shiftContent(contentStart, contentLength, -1);
			this.data[sequenceStart] = 129;
			this.data[sequenceStart + 1] = contentLength;
		} else if (contentLength <= 65535) {
			this.data[sequenceStart] = 130;
			this.data[sequenceStart + 1] = contentLength >> 8;
			this.data[sequenceStart + 2] = contentLength;
		} else if (contentLength <= 16777215) {
			this.shiftContent(contentStart, contentLength, 1);
			this.data[sequenceStart] = 131;
			this.data[sequenceStart + 1] = contentLength >> 16;
			this.data[sequenceStart + 2] = contentLength >> 8;
			this.data[sequenceStart + 3] = contentLength;
		} else throw new InvalidAsn1Error("Sequence too long");
	}
	encodeOidOctet(bytes, octet) {
		if (octet < 128) bytes.push(octet);
		else if (octet < 16384) {
			bytes.push(octet >>> 7 | 128);
			bytes.push(octet & 127);
		} else if (octet < 2097152) {
			bytes.push(octet >>> 14 | 128);
			bytes.push((octet >>> 7 | 128) & 255);
			bytes.push(octet & 127);
		} else if (octet < 268435456) {
			bytes.push(octet >>> 21 | 128);
			bytes.push((octet >>> 14 | 128) & 255);
			bytes.push((octet >>> 7 | 128) & 255);
			bytes.push(octet & 127);
		} else {
			bytes.push((octet >>> 28 | 128) & 255);
			bytes.push((octet >>> 21 | 128) & 255);
			bytes.push((octet >>> 14 | 128) & 255);
			bytes.push((octet >>> 7 | 128) & 255);
			bytes.push(octet & 127);
		}
	}
	shiftContent(start, length, shift) {
		this.data.copy(this.data, start + shift, start, start + length);
		this.currentOffset += shift;
	}
	ensureCapacity(needed) {
		if (this.size - this.currentOffset < needed) {
			let newSize = this.size * this.growthFactor;
			if (newSize - this.currentOffset < needed) newSize += needed;
			const newBuffer = Buffer.alloc(newSize);
			this.data.copy(newBuffer, 0, 0, this.currentOffset);
			this.data = newBuffer;
			this.size = newSize;
		}
	}
};
//#endregion
//#region src/controls/Control.ts
var Control = class {
	type;
	critical;
	responseType;
	constructor(type, options = {}) {
		this.type = type;
		this.critical = options.critical === true;
		this.responseType = options.responseType ?? type;
	}
	write(writer) {
		writer.startSequence();
		writer.writeString(this.type);
		writer.writeBoolean(this.critical);
		this.writeControl(writer);
		writer.endSequence();
	}
	parse(reader) {
		this.parseControl(reader);
	}
	writeControl(_) {}
	parseControl(_) {}
};
//#endregion
//#region src/controls/EntryChangeNotificationControl.ts
var EntryChangeNotificationControl = class EntryChangeNotificationControl extends Control {
	static type = "2.16.840.1.113730.3.4.7";
	value;
	constructor(options = {}) {
		super(EntryChangeNotificationControl.type, options);
		this.value = options.value;
	}
	parseControl(reader) {
		if (reader.readSequence()) {
			const changeType = reader.readInt() ?? 0;
			let previousDN;
			if (changeType === 8) previousDN = reader.readString();
			const changeNumber = reader.readInt() ?? 0;
			this.value = {
				changeType,
				previousDN,
				changeNumber
			};
		}
	}
	writeControl(writer) {
		if (!this.value) return;
		const controlWriter = new BerWriter();
		controlWriter.startSequence();
		controlWriter.writeInt(this.value.changeType);
		if (this.value.previousDN) controlWriter.writeString(this.value.previousDN);
		controlWriter.writeInt(this.value.changeNumber);
		controlWriter.endSequence();
		writer.writeBuffer(controlWriter.buffer, 4);
	}
};
//#endregion
//#region src/controls/PagedResultsControl.ts
var PagedResultsControl = class PagedResultsControl extends Control {
	static type = "1.2.840.113556.1.4.319";
	value;
	constructor(options = {}) {
		super(PagedResultsControl.type, options);
		this.value = options.value;
	}
	parseControl(reader) {
		if (reader.readSequence()) {
			const size = reader.readInt() ?? 0;
			const cookie = reader.readString(Ber.OctetString, true) ?? Buffer.alloc(0);
			this.value = {
				size,
				cookie
			};
		}
	}
	writeControl(writer) {
		if (!this.value) return;
		const controlWriter = new BerWriter();
		controlWriter.startSequence();
		controlWriter.writeInt(this.value.size);
		if (this.value.cookie?.length) controlWriter.writeBuffer(this.value.cookie, Ber.OctetString);
		else controlWriter.writeString("");
		controlWriter.endSequence();
		writer.writeBuffer(controlWriter.buffer, 4);
	}
};
//#endregion
//#region src/controls/PasswordPolicyControl.ts
/**
* Values of {@link PasswordPolicyValue.error}
*/
const PasswordPolicyError = {
	PasswordExpired: 0,
	AccountLocked: 1,
	ChangeAfterReset: 2,
	PasswordModNotAllowed: 3,
	MustSupplyOldPassword: 4,
	InsufficientPasswordQuality: 5,
	PasswordTooShort: 6,
	PasswordTooYoung: 7,
	PasswordInHistory: 8
};
/**
* Password policy control (draft-behera-ldap-password-policy). Send an instance without a value along with a `bind()`
* or `modify()` request, then read `value` from that same instance once the operation settles - it is populated from
* the server response, including when the operation throws. Sending the control again clears `value` first, so a
* reused instance only ever shows the latest response.
*/
var PasswordPolicyControl = class PasswordPolicyControl extends Control {
	static type = "1.3.6.1.4.1.42.2.27.8.5.1";
	value;
	constructor(options = {}) {
		super(PasswordPolicyControl.type, options);
		this.value = options.value;
	}
	parseControl(reader) {
		if (!reader.readSequence()) return;
		const value = {};
		if (reader.peek() === 160) {
			reader.readSequence(160);
			if (reader.peek() === 128) value.timeBeforeExpiration = reader.readTag(128) ?? 0;
			else if (reader.peek() === 129) value.graceAuthNsRemaining = reader.readTag(129) ?? 0;
		}
		if (reader.peek() === 129) value.error = reader.readTag(129) ?? 0;
		this.value = value;
	}
	writeControl(writer) {
		const { value } = this;
		this.value = void 0;
		if (!value) return;
		const controlWriter = new BerWriter();
		controlWriter.startSequence();
		if (typeof value.timeBeforeExpiration === "number") {
			controlWriter.startSequence(160);
			controlWriter.writeInt(value.timeBeforeExpiration, 128);
			controlWriter.endSequence();
		} else if (typeof value.graceAuthNsRemaining === "number") {
			controlWriter.startSequence(160);
			controlWriter.writeInt(value.graceAuthNsRemaining, 129);
			controlWriter.endSequence();
		}
		if (typeof value.error === "number") controlWriter.writeEnumeration(value.error, 129);
		controlWriter.endSequence();
		writer.writeBuffer(controlWriter.buffer, 4);
	}
};
//#endregion
//#region src/controls/PersistentSearchControl.ts
var PersistentSearchControl = class PersistentSearchControl extends Control {
	static type = "2.16.840.1.113730.3.4.3";
	value;
	constructor(options = {}) {
		super(PersistentSearchControl.type, options);
		this.value = options.value;
	}
	parseControl(reader) {
		if (reader.readSequence()) {
			const changeTypes = reader.readInt() ?? 0;
			const changesOnly = reader.readBoolean() ?? false;
			const returnECs = reader.readBoolean() ?? false;
			this.value = {
				changeTypes,
				changesOnly,
				returnECs
			};
		}
	}
	writeControl(writer) {
		if (!this.value) return;
		const controlWriter = new BerWriter();
		controlWriter.startSequence();
		controlWriter.writeInt(this.value.changeTypes);
		controlWriter.writeBoolean(this.value.changesOnly);
		controlWriter.writeBoolean(this.value.returnECs);
		controlWriter.endSequence();
		writer.writeBuffer(controlWriter.buffer, 4);
	}
};
//#endregion
//#region src/controls/ServerSideSortingRequestControl.ts
var ServerSideSortingRequestControl = class ServerSideSortingRequestControl extends Control {
	static type = "1.2.840.113556.1.4.473";
	static responseType = "1.2.840.113556.1.4.474";
	values;
	/**
	* Sort result reported by the server (RFC 2891 SortResult). Set on the instance sent with the search once the search
	* settles, cleared whenever the control is written again, and left undefined when the server sends no sort response.
	*/
	result;
	constructor(options = {}) {
		super(ServerSideSortingRequestControl.type, {
			...options,
			responseType: ServerSideSortingRequestControl.responseType
		});
		if (Array.isArray(options.value)) this.values = options.value;
		else if (typeof options.value === "object") this.values = [options.value];
		else this.values = [];
	}
	parseControl(reader) {
		if (!reader.readSequence(48)) return;
		if (reader.peek() === Ber.Enumeration) {
			const sortResult = reader.readEnumeration() ?? 0;
			this.result = reader.peek() === 128 ? {
				sortResult,
				attributeType: reader.readString(128) ?? ""
			} : { sortResult };
			return;
		}
		while (reader.readSequence(48)) {
			const attributeType = reader.readString() ?? "";
			let orderingRule = "";
			let reverseOrder = false;
			if (reader.peek() === 128) orderingRule = reader.readString(128) ?? "";
			if (reader.peek() === 129) reverseOrder = reader.readTag(129) !== 0;
			this.values.push({
				attributeType,
				orderingRule,
				reverseOrder
			});
		}
	}
	writeControl(writer) {
		this.result = void 0;
		if (!this.values.length) return;
		const controlWriter = new BerWriter();
		controlWriter.startSequence(48);
		for (const value of this.values) {
			controlWriter.startSequence(48);
			controlWriter.writeString(value.attributeType, Ber.OctetString);
			if (value.orderingRule) controlWriter.writeString(value.orderingRule, 128);
			if (typeof value.reverseOrder !== "undefined") controlWriter.writeBoolean(value.reverseOrder, 129);
			controlWriter.endSequence();
		}
		controlWriter.endSequence();
		writer.writeBuffer(controlWriter.buffer, 4);
	}
};
//#endregion
//#region src/dn/RDN.ts
/**
* RDN is a part of DN, and it consists of key & value pair. This class also supports
* compound RDNs, meaning that one RDN can hold multiple key & value pairs.
*/
var RDN = class {
	attrs = {};
	constructor(attrs) {
		if (attrs) for (const [key, value] of Object.entries(attrs)) this.set(key, value);
	}
	/**
	* Set an RDN pair.
	* @param {string} name
	* @param {string} value
	* @returns {object} RDN class
	*/
	set(name, value) {
		this.attrs[name] = value;
		return this;
	}
	/**
	* Get an RDN value at the specified name.
	* @param {string} name
	* @returns {string | undefined} value
	*/
	get(name) {
		return this.attrs[name];
	}
	/**
	* Checks, if this instance of RDN is equal to the other RDN.
	* @param {object} other
	* @returns true if equal; otherwise false
	*/
	equals(other) {
		const ourKeys = Object.keys(this.attrs);
		const otherKeys = Object.keys(other.attrs);
		if (ourKeys.length !== otherKeys.length) return false;
		ourKeys.sort();
		otherKeys.sort();
		for (const [i, key] of ourKeys.entries()) {
			if (key == null || key !== otherKeys[i]) return false;
			const ourValue = this.attrs[key];
			const otherValue = other.attrs[key];
			if (ourValue == null && otherValue == null) continue;
			if (ourValue == null || otherValue == null || ourValue !== otherValue) return false;
		}
		return true;
	}
	/**
	* Parse the RDN, escape values & return a string representation.
	* @returns {string} Escaped string representation of RDN.
	*/
	toString() {
		let str = "";
		for (const [key, value] of Object.entries(this.attrs)) {
			if (str) str += "+";
			str += `${key}=${this._escape(value)}`;
		}
		return str;
	}
	/**
	* Escape values & return a string representation.
	*
	* RFC defines, that these characters should be escaped:
	*
	* Comma                          ,
	* Backslash character            \
	* Pound sign (hash sign)         #
	* Plus sign                      +
	* Less than symbol               <
	* Greater than symbol            >
	* Semicolon                      ;
	* Double quote (quotation mark)  "
	* Equal sign                     =
	* Leading or trailing spaces
	* @param {string} value - RDN value to be escaped
	* @returns {string} Escaped string representation of RDN
	*/
	_escape(value = "") {
		let str = "";
		let current = 0;
		let quoted = false;
		const len = value.length;
		const escaped = /["\\]/;
		const special = /[#+,;<=>]/;
		if (len > 0) quoted = value.startsWith(" ") || value[len - 1] === " ";
		while (current < len) {
			const character = value[current] ?? "";
			if (escaped.test(character) || !quoted && special.test(character)) str += "\\";
			if (character) str += character;
			current += 1;
		}
		if (quoted) str = `"${str}"`;
		return str;
	}
};
//#endregion
//#region src/dn/DN.ts
/**
* DN class provides chain building of multiple RDNs, which can be later build into
* escaped string representation.
*/
var DN = class DN {
	rdns = [];
	constructor(rdns) {
		if (rdns) {
			if (Array.isArray(rdns)) this.rdns = rdns;
			else this.addRDNs(rdns);
		}
	}
	/**
	* Add an RDN component to the DN, consisting of key & value pair.
	* @param {string} key
	* @param {string} value
	* @returns {object} DN
	*/
	addPairRDN(key, value) {
		this.rdns.push(new RDN({ [key]: value }));
		return this;
	}
	/**
	* Add a single RDN component to the DN.
	*
	* Note, that this RDN can be compound (single RDN can have multiple key & value pairs).
	* @param {object} rdn
	* @returns {object} DN
	*/
	addRDN(rdn) {
		if (rdn instanceof RDN) this.rdns.push(rdn);
		else this.rdns.push(new RDN(rdn));
		return this;
	}
	/**
	* Add multiple RDN components to the DN.
	*
	* This method allows different interfaces to add RDNs into the DN.
	* It can:
	* - join other DN into this DN
	* - join list of RDNs or RDNAttributes into this DN
	* - create RDNs from object map, where every key & value will create a new RDN
	* @param {object|object[]} rdns
	* @returns {object} DN
	*/
	addRDNs(rdns) {
		if (rdns instanceof DN) this.rdns.push(...rdns.rdns);
		else if (Array.isArray(rdns)) for (const rdn of rdns) this.addRDN(rdn);
		else for (const [name, value] of Object.entries(rdns)) if (Array.isArray(value)) for (const rdnValue of value) this.rdns.push(new RDN({ [name]: rdnValue }));
		else this.rdns.push(new RDN({ [name]: value }));
		return this;
	}
	getRDNs() {
		return this.rdns;
	}
	get(index) {
		return this.rdns[index];
	}
	set(rdn, index) {
		if (rdn instanceof RDN) this.rdns[index] = rdn;
		else this.rdns[index] = new RDN(rdn);
		return this;
	}
	isEmpty() {
		return !this.rdns.length;
	}
	/**
	* Checks, if this instance of DN is equal to the other DN.
	* @param {object} other
	* @returns true if equal; otherwise false
	*/
	equals(other) {
		if (this.rdns.length !== other.rdns.length) return false;
		for (let i = 0; i < this.rdns.length; i += 1) {
			const rdn = this.rdns[i];
			const otherRdn = other.rdns[i];
			if (rdn == null && otherRdn == null) continue;
			if (rdn == null || otherRdn == null || !rdn.equals(otherRdn)) return false;
		}
		return true;
	}
	clone() {
		return new DN([...this.rdns]);
	}
	reverse() {
		this.rdns.reverse();
		return this;
	}
	pop() {
		return this.rdns.pop();
	}
	shift() {
		return this.rdns.shift();
	}
	/**
	* Parse the DN, escape values & return a string representation.
	* @returns String representation of DN
	*/
	toString() {
		let str = "";
		for (const rdn of this.rdns) {
			if (str.length) str += ",";
			str += rdn.toString();
		}
		return str;
	}
};
//#endregion
//#region src/errors/MessageParserError.ts
var MessageParserError = class MessageParserError extends Error {
	messageDetails;
	constructor(message) {
		super(message);
		this.name = "MessageParserError";
		Object.setPrototypeOf(this, MessageParserError.prototype);
	}
};
//#endregion
//#region src/errors/resultCodeErrors/ResultCodeError.ts
var ResultCodeError = class ResultCodeError extends Error {
	code;
	constructor(code, message) {
		super(`${message} Code: 0x${code.toString(16)}`);
		this.name = "ResultCodeError";
		this.code = code;
		Object.setPrototypeOf(this, ResultCodeError.prototype);
	}
};
//#endregion
//#region src/errors/resultCodeErrors/AdminLimitExceededError.ts
var AdminLimitExceededError = class AdminLimitExceededError extends ResultCodeError {
	constructor(message) {
		super(11, message ?? "An LDAP server limit set by an administrative authority has been exceeded.");
		this.name = "AdminLimitExceededError";
		Object.setPrototypeOf(this, AdminLimitExceededError.prototype);
	}
};
//#endregion
//#region src/errors/resultCodeErrors/AffectsMultipleDSAsError.ts
var AffectsMultipleDSAsError = class AffectsMultipleDSAsError extends ResultCodeError {
	constructor(message) {
		super(71, message ?? "The modify DN operation moves the entry from one LDAP server to another and thus requires more than one LDAP server.");
		this.name = "AffectsMultipleDSAsError";
		Object.setPrototypeOf(this, AffectsMultipleDSAsError.prototype);
	}
};
//#endregion
//#region src/errors/resultCodeErrors/AliasDerefProblemError.ts
var AliasDerefProblemError = class AliasDerefProblemError extends ResultCodeError {
	constructor(message) {
		super(36, message ?? "Either the client does not have access rights to read the aliased object's name or dereferencing is not allowed.");
		this.name = "AliasDerefProblemError";
		Object.setPrototypeOf(this, AliasDerefProblemError.prototype);
	}
};
//#endregion
//#region src/errors/resultCodeErrors/AliasProblemError.ts
var AliasProblemError = class AliasProblemError extends ResultCodeError {
	constructor(message) {
		super(33, message ?? "An error occurred when an alias was dereferenced.");
		this.name = "AliasProblemError";
		Object.setPrototypeOf(this, AliasProblemError.prototype);
	}
};
//#endregion
//#region src/errors/resultCodeErrors/AlreadyExistsError.ts
var AlreadyExistsError = class AlreadyExistsError extends ResultCodeError {
	constructor(message) {
		super(68, message ?? "The add operation attempted to add an entry that already exists, or that the modify operation attempted to rename an entry to the name of an entry that already exists.");
		this.name = "AlreadyExistsError";
		Object.setPrototypeOf(this, AlreadyExistsError.prototype);
	}
};
//#endregion
//#region src/errors/resultCodeErrors/AuthMethodNotSupportedError.ts
var AuthMethodNotSupportedError = class AuthMethodNotSupportedError extends ResultCodeError {
	constructor(message) {
		super(7, message ?? "The Directory Server does not support the requested Authentication Method.");
		this.name = "AuthMethodNotSupportedError";
		Object.setPrototypeOf(this, AuthMethodNotSupportedError.prototype);
	}
};
//#endregion
//#region src/errors/resultCodeErrors/BusyError.ts
var BusyError = class BusyError extends ResultCodeError {
	constructor(message) {
		super(51, message ?? "The LDAP server is too busy to process the client request at this time.");
		this.name = "BusyError";
		Object.setPrototypeOf(this, BusyError.prototype);
	}
};
//#endregion
//#region src/errors/resultCodeErrors/ConfidentialityRequiredError.ts
var ConfidentialityRequiredError = class ConfidentialityRequiredError extends ResultCodeError {
	constructor(message) {
		super(13, message ?? "The session is not protected by a protocol such as Transport Layer Security (TLS), which provides session confidentiality and the request will not be handled without confidentiality enabled.");
		this.name = "ConfidentialityRequiredError";
		Object.setPrototypeOf(this, ConfidentialityRequiredError.prototype);
	}
};
//#endregion
//#region src/errors/resultCodeErrors/ConstraintViolationError.ts
var ConstraintViolationError = class ConstraintViolationError extends ResultCodeError {
	constructor(message) {
		super(19, message ?? "The attribute value specified in a Add Request, Modify Request or ModifyDNRequest operation violates constraints placed on the attribute. The constraint can be one of size or content (string only, no binary).");
		this.name = "ConstraintViolationError";
		Object.setPrototypeOf(this, ConstraintViolationError.prototype);
	}
};
//#endregion
//#region src/errors/resultCodeErrors/InappropriateAuthError.ts
var InappropriateAuthError = class InappropriateAuthError extends ResultCodeError {
	constructor(message) {
		super(48, message ?? "The client is attempting to use an authentication method incorrectly.");
		this.name = "InappropriateAuthError";
		Object.setPrototypeOf(this, InappropriateAuthError.prototype);
	}
};
//#endregion
//#region src/errors/resultCodeErrors/InappropriateMatchingError.ts
var InappropriateMatchingError = class InappropriateMatchingError extends ResultCodeError {
	constructor(message) {
		super(18, message ?? "The matching rule specified in the search filter does not match a rule defined for the attribute's syntax.");
		this.name = "InappropriateMatchingError";
		Object.setPrototypeOf(this, InappropriateMatchingError.prototype);
	}
};
//#endregion
//#region src/errors/resultCodeErrors/InsufficientAccessError.ts
var InsufficientAccessError = class InsufficientAccessError extends ResultCodeError {
	constructor(message) {
		super(50, message ?? "The caller does not have sufficient rights to perform the requested operation.");
		this.name = "InsufficientAccessError";
		Object.setPrototypeOf(this, InsufficientAccessError.prototype);
	}
};
//#endregion
//#region src/errors/resultCodeErrors/InvalidCredentialsError.ts
var InvalidCredentialsError = class InvalidCredentialsError extends ResultCodeError {
	constructor(message) {
		super(49, message ?? "Invalid credentials during a bind operation.");
		this.name = "InvalidCredentialsError";
		Object.setPrototypeOf(this, InvalidCredentialsError.prototype);
	}
};
//#endregion
//#region src/errors/resultCodeErrors/InvalidDNSyntaxError.ts
var InvalidDNSyntaxError = class InvalidDNSyntaxError extends ResultCodeError {
	constructor(message) {
		super(34, message ?? "The syntax of the DN is incorrect.");
		this.name = "InvalidDNSyntaxError";
		Object.setPrototypeOf(this, InvalidDNSyntaxError.prototype);
	}
};
//#endregion
//#region src/errors/resultCodeErrors/InvalidSyntaxError.ts
var InvalidSyntaxError = class InvalidSyntaxError extends ResultCodeError {
	constructor(message) {
		super(21, message ?? "The attribute value specified in an Add Request, Compare Request, or Modify Request operation is an unrecognized or invalid syntax for the attribute.");
		this.name = "InvalidSyntaxError";
		Object.setPrototypeOf(this, InvalidSyntaxError.prototype);
	}
};
//#endregion
//#region src/errors/resultCodeErrors/IsLeafError.ts
var IsLeafError = class IsLeafError extends ResultCodeError {
	constructor(message) {
		super(35, message ?? "The specified operation cannot be performed on a leaf entry.");
		this.name = "IsLeafError";
		Object.setPrototypeOf(this, IsLeafError.prototype);
	}
};
//#endregion
//#region src/errors/resultCodeErrors/LoopDetectError.ts
var LoopDetectError = class LoopDetectError extends ResultCodeError {
	constructor(message) {
		super(54, message ?? "The client discovered an alias or LDAP Referral loop, and is thus unable to complete this request.");
		this.name = "LoopDetectError";
		Object.setPrototypeOf(this, LoopDetectError.prototype);
	}
};
//#endregion
//#region src/errors/resultCodeErrors/MoreResultsToReturnError.ts
var MoreResultsToReturnError = class MoreResultsToReturnError extends ResultCodeError {
	constructor(message) {
		super(95, message);
		this.name = "MoreResultsToReturnError";
		Object.setPrototypeOf(this, MoreResultsToReturnError.prototype);
	}
};
//#endregion
//#region src/errors/resultCodeErrors/NamingViolationError.ts
var NamingViolationError = class NamingViolationError extends ResultCodeError {
	constructor(message) {
		super(64, message ?? "The Add Request or Modify DN Request operation violates the schema's structure rules.");
		this.name = "NamingViolationError";
		Object.setPrototypeOf(this, NamingViolationError.prototype);
	}
};
//#endregion
//#region src/errors/resultCodeErrors/NoObjectClassModsError.ts
var NoObjectClassModsError = class NoObjectClassModsError extends ResultCodeError {
	constructor(message) {
		super(69, message ?? "The modify operation attempted to modify the structure rules of an object class.");
		this.name = "NoObjectClassModsError";
		Object.setPrototypeOf(this, NoObjectClassModsError.prototype);
	}
};
//#endregion
//#region src/errors/resultCodeErrors/NoSuchAttributeError.ts
var NoSuchAttributeError = class NoSuchAttributeError extends ResultCodeError {
	constructor(message) {
		super(16, message ?? "The attribute specified in the Modify Request or Compare Request operation does not exist in the entry.");
		this.name = "NoSuchAttributeError";
		Object.setPrototypeOf(this, NoSuchAttributeError.prototype);
	}
};
//#endregion
//#region src/errors/resultCodeErrors/NoSuchObjectError.ts
var NoSuchObjectError = class NoSuchObjectError extends ResultCodeError {
	constructor(message) {
		super(32, message ?? "The target object cannot be found.");
		this.name = "NoSuchObjectError";
		Object.setPrototypeOf(this, NoSuchObjectError.prototype);
	}
};
//#endregion
//#region src/errors/resultCodeErrors/NotAllowedOnNonLeafError.ts
var NotAllowedOnNonLeafError = class NotAllowedOnNonLeafError extends ResultCodeError {
	constructor(message) {
		super(66, message ?? "The requested operation is permitted only on leaf entries.");
		this.name = "NotAllowedOnNonLeafError";
		Object.setPrototypeOf(this, NotAllowedOnNonLeafError.prototype);
	}
};
//#endregion
//#region src/errors/resultCodeErrors/NotAllowedOnRDNError.ts
var NotAllowedOnRDNError = class NotAllowedOnRDNError extends ResultCodeError {
	constructor(message) {
		super(67, message ?? "The modify operation attempted to remove an attribute value that forms the entry's relative distinguished name.");
		this.name = "NotAllowedOnRDNError";
		Object.setPrototypeOf(this, NotAllowedOnRDNError.prototype);
	}
};
//#endregion
//#region src/errors/resultCodeErrors/NoResultError.ts
var NoResultError = class NoResultError extends ResultCodeError {
	constructor(message) {
		super(248, message ?? "No result message for the request.");
		this.name = "NoResultError";
		Object.setPrototypeOf(this, NoResultError.prototype);
	}
};
//#endregion
//#region src/errors/resultCodeErrors/ObjectClassViolationError.ts
var ObjectClassViolationError = class ObjectClassViolationError extends ResultCodeError {
	constructor(message) {
		super(65, message ?? "The Add Request, Modify Request, or modify DN operation violates the object class rules for the entry.");
		this.name = "ObjectClassViolationError";
		Object.setPrototypeOf(this, ObjectClassViolationError.prototype);
	}
};
//#endregion
//#region src/errors/resultCodeErrors/OperationsError.ts
var OperationsError = class OperationsError extends ResultCodeError {
	constructor(message) {
		super(1, message ?? "Request was out of sequence with another operation in progress.");
		this.name = "OperationsError";
		Object.setPrototypeOf(this, OperationsError.prototype);
	}
};
//#endregion
//#region src/errors/resultCodeErrors/ProtocolError.ts
var ProtocolError = class ProtocolError extends ResultCodeError {
	constructor(message) {
		super(2, message ?? "Client sent data to the server that did not comprise a valid LDAP request.");
		this.name = "ProtocolError";
		Object.setPrototypeOf(this, ProtocolError.prototype);
	}
};
//#endregion
//#region src/errors/resultCodeErrors/ResultsTooLargeError.ts
var ResultsTooLargeError = class ResultsTooLargeError extends ResultCodeError {
	constructor(message) {
		super(70, message ?? "Results are too large.");
		this.name = "ResultsTooLargeError";
		Object.setPrototypeOf(this, ResultsTooLargeError.prototype);
	}
};
//#endregion
//#region src/errors/resultCodeErrors/SaslBindInProgressError.ts
var SaslBindInProgressError = class SaslBindInProgressError extends ResultCodeError {
	response;
	constructor(response) {
		super(14, response.errorMessage || "The server is ready for the next step in the SASL authentication process. The client must send the server the same SASL Mechanism to continue the process.");
		this.response = response;
		this.name = "SaslBindInProgressError";
		Object.setPrototypeOf(this, SaslBindInProgressError.prototype);
	}
};
//#endregion
//#region src/errors/resultCodeErrors/SizeLimitExceededError.ts
var SizeLimitExceededError = class SizeLimitExceededError extends ResultCodeError {
	constructor(message) {
		super(4, message ?? "There were more entries matching the criteria contained in a SearchRequest operation than were allowed to be returned by the size limit configuration.");
		this.name = "SizeLimitExceededError";
		Object.setPrototypeOf(this, SizeLimitExceededError.prototype);
	}
};
//#endregion
//#region src/errors/resultCodeErrors/StrongAuthRequiredError.ts
var StrongAuthRequiredError = class StrongAuthRequiredError extends ResultCodeError {
	constructor(message) {
		super(8, message ?? "Client requested an operation that requires strong authentication.");
		this.name = "StrongAuthRequiredError";
		Object.setPrototypeOf(this, StrongAuthRequiredError.prototype);
	}
};
//#endregion
//#region src/errors/resultCodeErrors/TimeLimitExceededError.ts
var TimeLimitExceededError = class TimeLimitExceededError extends ResultCodeError {
	constructor(message) {
		super(3, message ?? "Processing on the associated request Timeout limit specified by either the client request or the server administration limits has been exceeded and has been terminated because it took too long to complete.");
		this.name = "TimeLimitExceededError";
		Object.setPrototypeOf(this, TimeLimitExceededError.prototype);
	}
};
//#endregion
//#region src/errors/resultCodeErrors/TLSNotSupportedError.ts
var TLSNotSupportedError = class TLSNotSupportedError extends ResultCodeError {
	constructor(message) {
		super(112, message ?? "TLS is not supported on the server.");
		this.name = "TLSNotSupportedError";
		Object.setPrototypeOf(this, TLSNotSupportedError.prototype);
	}
};
//#endregion
//#region src/errors/resultCodeErrors/TypeOrValueExistsError.ts
var TypeOrValueExistsError = class TypeOrValueExistsError extends ResultCodeError {
	constructor(message) {
		super(20, message ?? "The attribute value specified in a Add Request or Modify Request operation already exists as a value for that attribute.");
		this.name = "TypeOrValueExistsError";
		Object.setPrototypeOf(this, TypeOrValueExistsError.prototype);
	}
};
//#endregion
//#region src/errors/resultCodeErrors/UnavailableCriticalExtensionError.ts
var UnavailableCriticalExtensionError = class UnavailableCriticalExtensionError extends ResultCodeError {
	constructor(message) {
		super(12, message ?? "One or more critical extensions were not available by the LDAP server. Either the server does not support the control or the control is not appropriate for the operation type.");
		this.name = "UnavailableCriticalExtensionError";
		Object.setPrototypeOf(this, UnavailableCriticalExtensionError.prototype);
	}
};
//#endregion
//#region src/errors/resultCodeErrors/UnavailableError.ts
var UnavailableError = class UnavailableError extends ResultCodeError {
	constructor(message) {
		super(52, message ?? "The LDAP server cannot process the client's bind request.");
		this.name = "UnavailableError";
		Object.setPrototypeOf(this, UnavailableError.prototype);
	}
};
//#endregion
//#region src/errors/resultCodeErrors/UndefinedTypeError.ts
var UndefinedTypeError = class UndefinedTypeError extends ResultCodeError {
	constructor(message) {
		super(17, message ?? "The attribute specified in the modify or add operation does not exist in the LDAP server's schema.");
		this.name = "UndefinedTypeError";
		Object.setPrototypeOf(this, UndefinedTypeError.prototype);
	}
};
//#endregion
//#region src/errors/resultCodeErrors/UnknownStatusCodeError.ts
var UnknownStatusCodeError = class UnknownStatusCodeError extends ResultCodeError {
	constructor(code, message) {
		super(code, message ?? "Unknown error.");
		this.name = "UnknownStatusCodeError";
		Object.setPrototypeOf(this, UnknownStatusCodeError.prototype);
	}
};
//#endregion
//#region src/errors/resultCodeErrors/UnwillingToPerformError.ts
var UnwillingToPerformError = class UnwillingToPerformError extends ResultCodeError {
	constructor(message) {
		super(53, message ?? "The LDAP server cannot process the request because of server-defined restrictions.");
		this.name = "UnwillingToPerformError";
		Object.setPrototypeOf(this, UnwillingToPerformError.prototype);
	}
};
//#endregion
//#region src/filters/Filter.ts
var Filter = class {
	write(writer) {
		writer.startSequence(this.type);
		this.writeFilter(writer);
		writer.endSequence();
	}
	parse(reader) {
		this.parseFilter(reader);
	}
	matches(_ = {}, __) {
		return true;
	}
	/**
	* RFC 2254 Escaping of filter strings
	* Raw                     Escaped
	* (o=Parens (R Us))       (o=Parens \28R Us\29)
	* (cn=star*)              (cn=star\2A)
	* (filename=C:\MyFile)    (filename=C:\5cMyFile)
	* @param {string|Buffer} input
	* @returns Escaped string
	*/
	static escape(input) {
		let escapedResult = "";
		if (Buffer.isBuffer(input)) for (const inputChar of input) if (inputChar < 16) escapedResult += `\\0${inputChar.toString(16)}`;
		else escapedResult += `\\${inputChar.toString(16)}`;
		else for (const inputChar of input) switch (inputChar) {
			case "*":
				escapedResult += "\\2a";
				break;
			case "(":
				escapedResult += "\\28";
				break;
			case ")":
				escapedResult += "\\29";
				break;
			case "\\":
				escapedResult += "\\5c";
				break;
			case "\0":
				escapedResult += "\\00";
				break;
			default: escapedResult += inputChar;
		}
		return escapedResult;
	}
	parseFilter(_) {}
	writeFilter(_) {}
	getObjectValue(objectToCheck, key, strictAttributeCase) {
		let objectKey;
		if (typeof objectToCheck[key] !== "undefined") objectKey = key;
		else if (!strictAttributeCase && key.toLowerCase() === "objectclass") {
			for (const objectToCheckKey of Object.keys(objectToCheck)) if (objectToCheckKey.toLowerCase() === key.toLowerCase()) {
				objectKey = objectToCheckKey;
				break;
			}
		}
		if (objectKey) return objectToCheck[objectKey];
	}
};
//#endregion
//#region src/filters/escapeFilter.ts
/**
* Tagged template literal for building LDAP filter strings. Every interpolated value is escaped
* with {@link Filter.escape} (RFC 2254 / RFC 4515), which prevents filter syntax characters in
* untrusted input from being misinterpreted as syntax (injection attacks).
* @example
* const filter = escapeFilter`(&(objectClass=user)(uid=${untrustedInput}))`;
* @param {TemplateStringsArray} strings - Literal portions of the template
* @param {...Buffer|boolean|number|string} values - Values to escape before interpolating
* @returns {string} Filter string with all interpolated values escaped
*/
function escapeFilter(strings, ...values) {
	let result = strings[0] ?? "";
	for (const [index, value] of values.entries()) {
		result += Filter.escape(typeof value === "string" || Buffer.isBuffer(value) ? value : String(value));
		result += strings[index + 1] ?? "";
	}
	return result;
}
//#endregion
//#region src/SearchFilter.ts
const SearchFilter = {
	and: 160,
	or: 161,
	not: 162,
	equalityMatch: 163,
	substrings: 164,
	greaterOrEqual: 165,
	lessOrEqual: 166,
	present: 135,
	approxMatch: 168,
	extensibleMatch: 169
};
//#endregion
//#region src/filters/AndFilter.ts
var AndFilter = class extends Filter {
	type = SearchFilter.and;
	filters;
	constructor(options) {
		super();
		this.filters = options.filters;
	}
	writeFilter(writer) {
		for (const filter of this.filters) filter.write(writer);
	}
	matches(objectToCheck = {}, strictAttributeCase) {
		if (!this.filters.length) return true;
		for (const filter of this.filters) if (!filter.matches(objectToCheck, strictAttributeCase)) return false;
		return true;
	}
	toString() {
		let result = "(&";
		for (const filter of this.filters) result += filter.toString();
		result += ")";
		return result;
	}
};
//#endregion
//#region src/filters/ApproximateFilter.ts
var ApproximateFilter = class extends Filter {
	type = SearchFilter.approxMatch;
	attribute;
	value;
	constructor(options = {}) {
		super();
		this.attribute = options.attribute ?? "";
		this.value = options.value ?? "";
	}
	parseFilter(reader) {
		this.attribute = (reader.readString() ?? "").toLowerCase();
		this.value = reader.readString() ?? "";
	}
	writeFilter(writer) {
		writer.writeString(this.attribute);
		writer.writeString(this.value);
	}
	matches(_ = {}, __) {
		throw new Error("Approximate match implementation unknown");
	}
	toString() {
		return `(${Filter.escape(this.attribute)}~=${Filter.escape(this.value)})`;
	}
};
//#endregion
//#region src/filters/EqualityFilter.ts
var EqualityFilter = class extends Filter {
	type = SearchFilter.equalityMatch;
	attribute;
	value;
	constructor(options = {}) {
		super();
		this.attribute = options.attribute ?? "";
		this.value = options.value ?? "";
	}
	parseFilter(reader) {
		this.attribute = (reader.readString() ?? "").toLowerCase();
		this.value = reader.readString() ?? "";
		if (this.attribute === "objectclass") this.value = this.value.toLowerCase();
	}
	writeFilter(writer) {
		writer.writeString(this.attribute);
		if (Buffer.isBuffer(this.value)) writer.writeBuffer(this.value, Ber.OctetString);
		else writer.writeString(this.value);
	}
	matches(objectToCheck = {}, strictAttributeCase) {
		const objectToCheckValue = this.getObjectValue(objectToCheck, this.attribute, strictAttributeCase);
		if (typeof objectToCheckValue !== "undefined") {
			if (Buffer.isBuffer(this.value) && Buffer.isBuffer(objectToCheckValue)) return this.value === objectToCheckValue;
			const stringValue = Buffer.isBuffer(this.value) ? this.value.toString("utf8") : this.value;
			if (strictAttributeCase) return stringValue === objectToCheckValue;
			return stringValue.toLowerCase() === objectToCheckValue.toLowerCase();
		}
		return false;
	}
	toString() {
		return `(${Filter.escape(this.attribute)}=${Filter.escape(this.value)})`;
	}
};
//#endregion
//#region src/filters/ExtensibleFilter.ts
var ExtensibleFilter = class extends Filter {
	type = SearchFilter.extensibleMatch;
	value;
	rule;
	matchType;
	dnAttributes;
	constructor(options = {}) {
		super();
		this.matchType = options.matchType ?? "";
		this.rule = options.rule ?? "";
		this.dnAttributes = options.dnAttributes === true;
		this.value = options.value ?? "";
	}
	parseFilter(reader) {
		const end = reader.offset + reader.length;
		while (reader.offset < end) {
			const tag = reader.peek();
			switch (tag) {
				case 129:
					this.rule = reader.readString(tag) ?? "";
					break;
				case 130:
					this.matchType = reader.readString(tag) ?? "";
					break;
				case 131:
					this.value = reader.readString(tag) ?? "";
					break;
				case 132:
					this.dnAttributes = reader.readBoolean() ?? false;
					break;
				default: {
					let type = "<null>";
					if (tag) type = `0x${tag.toString(16)}`;
					throw new Error(`Invalid ext_match filter type: ${type}`);
				}
			}
		}
	}
	writeFilter(writer) {
		if (this.rule) writer.writeString(this.rule, 129);
		if (this.matchType) writer.writeString(this.matchType, 130);
		writer.writeString(this.value, 131);
		if (this.dnAttributes) writer.writeBoolean(this.dnAttributes, 132);
	}
	matches(_ = {}, __) {
		throw new Error("Approximate match implementation unknown");
	}
	toString() {
		let result = `(${Filter.escape(this.matchType)}:`;
		if (this.dnAttributes) result += "dn:";
		if (this.rule) result += `${Filter.escape(this.rule)}:`;
		result += `=${Filter.escape(this.value)})`;
		return result;
	}
};
//#endregion
//#region src/filters/GreaterThanEqualsFilter.ts
var GreaterThanEqualsFilter = class extends Filter {
	type = SearchFilter.greaterOrEqual;
	attribute;
	value;
	constructor(options = {}) {
		super();
		this.attribute = options.attribute ?? "";
		this.value = options.value ?? "";
	}
	parseFilter(reader) {
		this.attribute = reader.readString()?.toLowerCase() ?? "";
		this.value = reader.readString() ?? "";
	}
	writeFilter(writer) {
		writer.writeString(this.attribute);
		writer.writeString(this.value);
	}
	matches(objectToCheck = {}, strictAttributeCase) {
		const objectToCheckValue = this.getObjectValue(objectToCheck, this.attribute, strictAttributeCase);
		if (typeof objectToCheckValue !== "undefined") {
			if (strictAttributeCase) return objectToCheckValue >= this.value;
			return objectToCheckValue.toLowerCase() >= this.value.toLowerCase();
		}
		return false;
	}
	toString() {
		return `(${Filter.escape(this.attribute)}>=${Filter.escape(this.value)})`;
	}
};
//#endregion
//#region src/filters/LessThanEqualsFilter.ts
var LessThanEqualsFilter = class extends Filter {
	type = SearchFilter.lessOrEqual;
	attribute;
	value;
	constructor(options = {}) {
		super();
		this.attribute = options.attribute ?? "";
		this.value = options.value ?? "";
	}
	parseFilter(reader) {
		this.attribute = reader.readString()?.toLowerCase() ?? "";
		this.value = reader.readString() ?? "";
	}
	writeFilter(writer) {
		writer.writeString(this.attribute);
		writer.writeString(this.value);
	}
	matches(objectToCheck = {}, strictAttributeCase) {
		const objectToCheckValue = this.getObjectValue(objectToCheck, this.attribute, strictAttributeCase);
		if (typeof objectToCheckValue !== "undefined") {
			if (strictAttributeCase) return objectToCheckValue <= this.value;
			return objectToCheckValue.toLowerCase() <= this.value.toLowerCase();
		}
		return false;
	}
	toString() {
		return `(${Filter.escape(this.attribute)}<=${Filter.escape(this.value)})`;
	}
};
//#endregion
//#region src/filters/NotFilter.ts
var NotFilter = class extends Filter {
	type = SearchFilter.not;
	filter;
	constructor(options) {
		super();
		this.filter = options.filter;
	}
	writeFilter(writer) {
		this.filter.write(writer);
	}
	matches(objectToCheck = {}, strictAttributeCase) {
		return !this.filter.matches(objectToCheck, strictAttributeCase);
	}
	toString() {
		return `(!${this.filter.toString()})`;
	}
};
//#endregion
//#region src/filters/OrFilter.ts
var OrFilter = class extends Filter {
	type = SearchFilter.or;
	filters;
	constructor(options) {
		super();
		this.filters = options.filters;
	}
	writeFilter(writer) {
		for (const filter of this.filters) filter.write(writer);
	}
	matches(objectToCheck = {}, strictAttributeCase) {
		if (!this.filters.length) return true;
		for (const filter of this.filters) if (filter.matches(objectToCheck, strictAttributeCase)) return true;
		return false;
	}
	toString() {
		let result = "(|";
		for (const filter of this.filters) result += filter.toString();
		result += ")";
		return result;
	}
};
//#endregion
//#region src/filters/PresenceFilter.ts
var PresenceFilter = class extends Filter {
	type = SearchFilter.present;
	attribute;
	constructor(options = {}) {
		super();
		this.attribute = options.attribute ?? "";
	}
	parseFilter(reader) {
		this.attribute = reader.buffer.subarray(0, reader.length).toString("utf8").toLowerCase();
		reader.offset += reader.length;
	}
	writeFilter(writer) {
		for (let i = 0; i < this.attribute.length; i += 1) writer.writeByte(this.attribute.charCodeAt(i));
	}
	matches(objectToCheck = {}, strictAttributeCase) {
		return typeof this.getObjectValue(objectToCheck, this.attribute, strictAttributeCase) !== "undefined";
	}
	toString() {
		return `(${Filter.escape(this.attribute)}=*)`;
	}
};
//#endregion
//#region src/filters/SubstringFilter.ts
var SubstringFilter = class SubstringFilter extends Filter {
	type = SearchFilter.substrings;
	attribute;
	initial;
	any;
	final;
	constructor(options = {}) {
		super();
		this.attribute = options.attribute ?? "";
		this.initial = options.initial ?? "";
		this.any = options.any ?? [];
		this.final = options.final ?? "";
	}
	parseFilter(reader) {
		this.attribute = reader.readString()?.toLowerCase() ?? "";
		reader.readSequence();
		const end = reader.offset + reader.length;
		while (reader.offset < end) {
			const tag = reader.peek();
			switch (tag) {
				case 128:
					this.initial = reader.readString(tag) ?? "";
					if (this.attribute === "objectclass") this.initial = this.initial.toLowerCase();
					break;
				case 129: {
					let anyValue = reader.readString(tag) ?? "";
					if (this.attribute === "objectclass") anyValue = anyValue.toLowerCase();
					this.any.push(anyValue);
					break;
				}
				case 130:
					this.final = reader.readString(tag) ?? "";
					if (this.attribute === "objectclass") this.final = this.final.toLowerCase();
					break;
				default: {
					let type = "<null>";
					if (tag) type = `0x${tag.toString(16)}`;
					throw new Error(`Invalid substring filter type: ${type}`);
				}
			}
		}
	}
	writeFilter(writer) {
		writer.writeString(this.attribute);
		writer.startSequence();
		if (this.initial) writer.writeString(this.initial, 128);
		for (const anyItem of this.any) writer.writeString(anyItem, 129);
		if (this.final) writer.writeString(this.final, 130);
		writer.endSequence();
	}
	matches(objectToCheck = {}, strictAttributeCase) {
		const objectToCheckValue = this.getObjectValue(objectToCheck, this.attribute, strictAttributeCase);
		if (typeof objectToCheckValue !== "undefined") {
			let regexp = "";
			if (this.initial) regexp += `^${SubstringFilter._escapeRegExp(this.initial)}.*`;
			for (const anyItem of this.any) regexp += `${SubstringFilter._escapeRegExp(anyItem)}.*`;
			if (this.final) regexp += `${SubstringFilter._escapeRegExp(this.final)}$`;
			return new RegExp(regexp, strictAttributeCase ? "gmu" : "igmu").test(objectToCheckValue);
		}
		return false;
	}
	toString() {
		let result = `(${Filter.escape(this.attribute)}=${Filter.escape(this.initial)}*`;
		for (const anyItem of this.any) result += `${Filter.escape(anyItem)}*`;
		result += `${Filter.escape(this.final)})`;
		return result;
	}
	static _escapeRegExp(str) {
		return str.replace(/[$()*+./?[\\\]^{|}-]/g, "\\$&");
	}
};
//#endregion
//#region src/ProtocolOperation.ts
const ProtocolOperation = {
	LDAP_VERSION_3: 3,
	LBER_SET: 49,
	LDAP_CONTROLS: 160,
	LDAP_REQ_BIND: 96,
	LDAP_REQ_BIND_SASL: 163,
	LDAP_REQ_UNBIND: 66,
	LDAP_REQ_SEARCH: 99,
	LDAP_REQ_MODIFY: 102,
	LDAP_REQ_ADD: 104,
	LDAP_REQ_DELETE: 74,
	LDAP_REQ_MODRDN: 108,
	LDAP_REQ_COMPARE: 110,
	LDAP_REQ_ABANDON: 80,
	LDAP_REQ_EXTENSION: 119,
	LDAP_RES_BIND: 97,
	LDAP_RES_SEARCH_ENTRY: 100,
	LDAP_RES_SEARCH_REF: 115,
	LDAP_RES_SEARCH: 101,
	LDAP_RES_MODIFY: 103,
	LDAP_RES_ADD: 105,
	LDAP_RES_DELETE: 107,
	LDAP_RES_MODRDN: 109,
	LDAP_RES_COMPARE: 111,
	LDAP_RES_EXTENSION: 120
};
//#endregion
//#region src/ControlParser.ts
var ControlParser = class {
	static parse(reader, requestControls) {
		if (reader.readSequence() === null) return null;
		let type = "";
		let critical = false;
		let value = Buffer.alloc(0);
		if (reader.length) {
			const end = reader.offset + reader.length;
			type = reader.readString() ?? "";
			if (reader.offset < end) {
				if (reader.peek() === Ber.Boolean) critical = reader.readBoolean() ?? false;
			}
			if (reader.offset < end) value = reader.readString(Ber.OctetString, true) ?? Buffer.alloc(0);
		}
		let control;
		switch (type) {
			case EntryChangeNotificationControl.type:
				control = new EntryChangeNotificationControl({ critical });
				break;
			case PagedResultsControl.type:
				control = new PagedResultsControl({ critical });
				break;
			case PersistentSearchControl.type:
				control = new PersistentSearchControl({ critical });
				break;
			case ServerSideSortingRequestControl.type:
				control = new ServerSideSortingRequestControl({ critical });
				break;
			default: control = requestControls.find((requestControl) => requestControl.responseType === type);
		}
		if (!control) return null;
		const controlReader = new BerReader(value);
		control.parse(controlReader);
		return control;
	}
};
//#endregion
//#region src/messages/Message.ts
var Message = class {
	version = ProtocolOperation.LDAP_VERSION_3;
	messageId = 0;
	controls;
	constructor(options) {
		this.messageId = options.messageId;
		this.controls = options.controls;
	}
	write() {
		const writer = new BerWriter();
		writer.startSequence();
		writer.writeInt(this.messageId);
		writer.startSequence(this.protocolOperation);
		this.writeMessage(writer);
		writer.endSequence();
		if (this.controls?.length) {
			writer.startSequence(ProtocolOperation.LDAP_CONTROLS);
			for (const control of this.controls) control.write(writer);
			writer.endSequence();
		}
		writer.endSequence();
		return writer.buffer;
	}
	parse(reader, requestControls) {
		this.controls = [];
		this.parseMessage(reader);
		if (reader.peek() === ProtocolOperation.LDAP_CONTROLS) {
			reader.readSequence();
			const end = reader.offset + reader.length;
			while (reader.offset < end) {
				const control = ControlParser.parse(reader, requestControls);
				if (control) this.controls.push(control);
			}
		}
	}
	toString() {
		return JSON.stringify({
			messageId: this.messageId,
			messageType: this.constructor.name
		}, null, 2);
	}
	parseMessage(_) {}
	writeMessage(_) {}
};
//#endregion
//#region src/messages/AbandonRequest.ts
var AbandonRequest = class extends Message {
	protocolOperation;
	abandonId;
	constructor(options) {
		super(options);
		this.protocolOperation = ProtocolOperation.LDAP_REQ_ABANDON;
		this.abandonId = options.abandonId ?? 0;
	}
	writeMessage(writer) {
		let i = this.abandonId;
		let intSize = 4;
		const mask = 4286578688;
		while (((i & mask) === 0 || (i & mask) === mask) && intSize > 1) {
			intSize -= 1;
			i <<= 8;
		}
		node_assert.ok(intSize <= 4);
		while (intSize-- > 0) {
			writer.writeByte((i & 4278190080) >> 24);
			i <<= 8;
		}
	}
	parseMessage(reader) {
		const { length } = reader;
		if (length) {
			let offset = 1;
			let value;
			const fb = reader.buffer[offset] ?? 0;
			value = fb & 127;
			for (let i = 1; i < length; i += 1) {
				value <<= 8;
				offset += 1;
				const bufferValue = reader.buffer[offset] ?? 0;
				value |= bufferValue & 255;
			}
			if ((fb & 128) === 128) value = -value;
			reader.offset += length;
			this.abandonId = value;
		} else this.abandonId = 0;
	}
};
//#endregion
//#region src/Attribute.ts
const utfDecoder = new node_util.TextDecoder("utf8", { fatal: true });
var Attribute = class {
	buffers = [];
	type;
	values;
	constructor(options = {}) {
		this.type = options.type ?? "";
		this.values = options.values ?? [];
	}
	get parsedBuffers() {
		return this.buffers;
	}
	write(writer) {
		writer.startSequence();
		const { type } = this;
		writer.writeString(type);
		writer.startSequence(ProtocolOperation.LBER_SET);
		if (this.values.length) for (const value of this.values) if (Buffer.isBuffer(value)) writer.writeBuffer(value, Ber.OctetString);
		else writer.writeString(value);
		else writer.writeStringArray([]);
		writer.endSequence();
		writer.endSequence();
	}
	parse(reader) {
		reader.readSequence();
		this.type = reader.readString() ?? "";
		const isBinaryType = this._isBinaryType();
		if (reader.peek() === ProtocolOperation.LBER_SET) {
			if (reader.readSequence(ProtocolOperation.LBER_SET)) {
				const end = reader.offset + reader.length;
				while (reader.offset < end) {
					const buffer = reader.readString(Ber.OctetString, true) ?? Buffer.alloc(0);
					this.buffers.push(buffer);
					if (isBinaryType) this.values.push(buffer);
					else try {
						const decoded = utfDecoder.decode(buffer);
						this.values.push(decoded);
					} catch {
						this.values.push(buffer);
					}
				}
			}
		}
	}
	_isBinaryType() {
		return /;binary$/i.test(this.type || "");
	}
};
//#endregion
//#region src/messages/AddRequest.ts
var AddRequest = class extends Message {
	protocolOperation;
	dn;
	attributes;
	constructor(options) {
		super(options);
		this.protocolOperation = ProtocolOperation.LDAP_REQ_ADD;
		this.dn = options.dn;
		this.attributes = options.attributes ?? [];
	}
	writeMessage(writer) {
		writer.writeString(this.dn);
		writer.startSequence();
		for (const attribute of this.attributes) attribute.write(writer);
		writer.endSequence();
	}
	parseMessage(reader) {
		this.dn = reader.readString() ?? "";
		reader.readSequence();
		const end = reader.offset + reader.length;
		while (reader.offset < end) {
			const attribute = new Attribute();
			attribute.parse(reader);
			this.attributes.push(attribute);
		}
	}
};
//#endregion
//#region src/messages/MessageResponse.ts
var MessageResponse = class extends Message {
	status;
	matchedDN;
	errorMessage;
	constructor(options) {
		super(options);
		this.status = options.status ?? 0;
		this.matchedDN = options.matchedDN ?? "";
		this.errorMessage = options.errorMessage ?? "";
	}
	parseMessage(reader) {
		this.status = reader.readEnumeration() ?? 0;
		this.matchedDN = reader.readString() ?? "";
		this.errorMessage = reader.readString() ?? "";
	}
};
//#endregion
//#region src/messages/AddResponse.ts
var AddResponse = class extends MessageResponse {
	protocolOperation;
	constructor(options) {
		super(options);
		this.protocolOperation = ProtocolOperation.LDAP_RES_ADD;
	}
};
//#endregion
//#region src/messages/BindRequest.ts
const SASL_MECHANISMS = [
	"EXTERNAL",
	"PLAIN",
	"DIGEST-MD5",
	"SCRAM-SHA-1"
];
var BindRequest = class extends Message {
	protocolOperation;
	dn;
	password;
	mechanism;
	constructor(options) {
		super(options);
		this.protocolOperation = ProtocolOperation.LDAP_REQ_BIND;
		this.dn = options.dn ?? "";
		this.password = options.password ?? "";
		this.mechanism = options.mechanism;
	}
	writeMessage(writer) {
		writer.writeInt(this.version);
		writer.writeString(this.dn);
		if (this.mechanism) {
			writer.startSequence(ProtocolOperation.LDAP_REQ_BIND_SASL);
			writer.writeString(this.mechanism);
			writer.writeString(this.password);
			writer.endSequence();
		} else writer.writeString(this.password, Ber.Context);
	}
	parseMessage(reader) {
		this.version = reader.readInt() ?? ProtocolOperation.LDAP_VERSION_3;
		this.dn = reader.readString() ?? "";
		const contextCheck = reader.peek();
		if (contextCheck !== Ber.Context) {
			let type = "<null>";
			if (contextCheck) type = `0x${contextCheck.toString(16)}`;
			throw new Error(`Authentication type not supported: ${type}`);
		}
		this.password = reader.readString(Ber.Context) ?? "";
	}
};
//#endregion
//#region src/messages/BindResponse.ts
var BindResponse = class extends MessageResponse {
	protocolOperation;
	data = [];
	constructor(options) {
		super(options);
		this.protocolOperation = ProtocolOperation.LDAP_RES_BIND;
	}
	parseMessage(reader) {
		super.parseMessage(reader);
		while (reader.remain > 0) {
			const type = reader.peek();
			if (type === ProtocolOperation.LDAP_CONTROLS) break;
			this.data.push(reader.readString(typeof type === "number" ? type : void 0) ?? "");
		}
	}
};
//#endregion
//#region src/messages/CompareRequest.ts
var CompareRequest = class extends Message {
	protocolOperation;
	dn;
	attribute;
	value;
	constructor(options) {
		super(options);
		this.protocolOperation = ProtocolOperation.LDAP_REQ_COMPARE;
		this.attribute = options.attribute ?? "";
		this.value = options.value ?? "";
		this.dn = options.dn ?? "";
	}
	writeMessage(writer) {
		writer.writeString(this.dn);
		writer.startSequence();
		writer.writeString(this.attribute);
		writer.writeString(this.value);
		writer.endSequence();
	}
	parseMessage(reader) {
		this.dn = reader.readString() ?? "";
		reader.readSequence();
		this.attribute = (reader.readString() ?? "").toLowerCase();
		this.value = reader.readString() ?? "";
	}
};
//#endregion
//#region src/messages/CompareResponse.ts
let CompareResult = /* @__PURE__ */ function(CompareResult) {
	/**
	* Indicates that the target entry exists and contains the specified attribute with the indicated value
	*/
	CompareResult[CompareResult["compareTrue"] = 6] = "compareTrue";
	/**
	* Indicates that the target entry exists and contains the specified attribute, but that the attribute does not have the indicated value
	*/
	CompareResult[CompareResult["compareFalse"] = 5] = "compareFalse";
	/**
	* Indicates that the target entry exists but does not contain the specified attribute
	*/
	CompareResult[CompareResult["noSuchAttribute"] = 22] = "noSuchAttribute";
	/**
	* Indicates that the target entry does not exist
	*/
	CompareResult[CompareResult["noSuchObject"] = 50] = "noSuchObject";
	return CompareResult;
}({});
var CompareResponse = class extends MessageResponse {
	protocolOperation;
	constructor(options) {
		super(options);
		this.protocolOperation = ProtocolOperation.LDAP_RES_COMPARE;
	}
};
//#endregion
//#region src/messages/DeleteRequest.ts
var DeleteRequest = class extends Message {
	protocolOperation;
	dn;
	constructor(options) {
		super(options);
		this.protocolOperation = ProtocolOperation.LDAP_REQ_DELETE;
		this.dn = options.dn ?? "";
	}
	writeMessage(writer) {
		const buffer = Buffer.from(this.dn);
		for (const byte of buffer) writer.writeByte(byte);
	}
	parseMessage(reader) {
		const { length } = reader;
		this.dn = reader.buffer.subarray(0, length).toString("utf8");
		reader.offset += reader.length;
	}
};
//#endregion
//#region src/messages/DeleteResponse.ts
var DeleteResponse = class extends MessageResponse {
	protocolOperation;
	constructor(options) {
		super(options);
		this.protocolOperation = ProtocolOperation.LDAP_RES_DELETE;
	}
};
//#endregion
//#region src/messages/ExtendedRequest.ts
var ExtendedRequest = class extends Message {
	protocolOperation;
	oid;
	value;
	constructor(options) {
		super(options);
		this.protocolOperation = ProtocolOperation.LDAP_REQ_EXTENSION;
		this.oid = options.oid ?? "";
		this.value = options.value ?? "";
	}
	writeMessage(writer) {
		writer.writeString(this.oid, 128);
		if (Buffer.isBuffer(this.value)) writer.writeBuffer(this.value, 129);
		else if (this.value) writer.writeString(this.value, 129);
	}
	parseMessage(reader) {
		this.oid = reader.readString(128) ?? "";
		if (reader.peek() === 129) try {
			this.value = reader.readString(129) ?? "";
		} catch {
			this.value = reader.readString(129, true) ?? Buffer.alloc(0);
		}
	}
};
//#endregion
//#region src/messages/ExtendedResponse.ts
const ExtendedResponseProtocolOperations = {
	oid: 138,
	value: 139
};
var ExtendedResponse = class extends MessageResponse {
	protocolOperation;
	oid;
	value;
	constructor(options) {
		super(options);
		this.protocolOperation = ProtocolOperation.LDAP_RES_EXTENSION;
		this.oid = options.oid;
		this.value = options.value;
	}
	parseMessage(reader) {
		super.parseMessage(reader);
		if (reader.peek() === ExtendedResponseProtocolOperations.oid) this.oid = reader.readString(ExtendedResponseProtocolOperations.oid) ?? "";
		if (reader.peek() === ExtendedResponseProtocolOperations.value) this.value = reader.readString(ExtendedResponseProtocolOperations.value) ?? void 0;
	}
};
//#endregion
//#region src/messages/ModifyDNRequest.ts
var ModifyDNRequest = class extends Message {
	protocolOperation;
	deleteOldRdn;
	dn;
	newRdn;
	newSuperior;
	constructor(options) {
		super(options);
		this.protocolOperation = ProtocolOperation.LDAP_REQ_MODRDN;
		this.deleteOldRdn = options.deleteOldRdn !== false;
		this.dn = options.dn ?? "";
		this.newRdn = options.newRdn ?? "";
		this.newSuperior = options.newSuperior ?? "";
	}
	writeMessage(writer) {
		writer.writeString(this.dn);
		writer.writeString(this.newRdn);
		writer.writeBoolean(this.deleteOldRdn);
		if (this.newSuperior) writer.writeString(this.newSuperior, 128);
	}
	parseMessage(reader) {
		this.dn = reader.readString() ?? "";
		this.newRdn = reader.readString() ?? "";
		this.deleteOldRdn = reader.readBoolean() ?? false;
		if (reader.peek() === 128) this.newSuperior = reader.readString(128) ?? "";
	}
};
//#endregion
//#region src/messages/ModifyDNResponse.ts
var ModifyDNResponse = class extends MessageResponse {
	protocolOperation;
	constructor(options) {
		super(options);
		this.protocolOperation = ProtocolOperation.LDAP_RES_MODRDN;
	}
};
//#endregion
//#region src/Change.ts
var Change = class {
	operation;
	modification;
	constructor(options = { modification: new Attribute() }) {
		this.operation = options.operation ?? "add";
		this.modification = options.modification;
	}
	write(writer) {
		writer.startSequence();
		switch (this.operation) {
			case "add":
				writer.writeEnumeration(0);
				break;
			case "delete":
				writer.writeEnumeration(1);
				break;
			case "replace":
				writer.writeEnumeration(2);
				break;
			default: throw new Error(`Unknown change operation: ${this.operation}`);
		}
		this.modification.write(writer);
		writer.endSequence();
	}
	parse(reader) {
		reader.readSequence();
		const operation = reader.readEnumeration();
		switch (operation) {
			case 0:
				this.operation = "add";
				break;
			case 1:
				this.operation = "delete";
				break;
			case 2:
				this.operation = "replace";
				break;
			case null: throw new Error(`Unknown change operation - <null> operation value`);
			default: throw new Error(`Unknown change operation: 0x${operation.toString(16)}`);
		}
		this.modification = new Attribute();
		this.modification.parse(reader);
	}
};
//#endregion
//#region src/messages/ModifyRequest.ts
var ModifyRequest = class extends Message {
	protocolOperation;
	dn;
	changes;
	constructor(options) {
		super(options);
		this.protocolOperation = ProtocolOperation.LDAP_REQ_MODIFY;
		this.dn = options.dn ?? "";
		this.changes = options.changes ?? [];
	}
	writeMessage(writer) {
		writer.writeString(this.dn);
		writer.startSequence();
		for (const change of this.changes) change.write(writer);
		writer.endSequence();
	}
	parseMessage(reader) {
		this.dn = reader.readString() ?? "";
		reader.readSequence();
		const end = reader.offset + reader.length;
		while (reader.offset < end) {
			const change = new Change();
			change.parse(reader);
			this.changes.push(change);
		}
	}
};
//#endregion
//#region src/messages/ModifyResponse.ts
var ModifyResponse = class extends MessageResponse {
	protocolOperation;
	constructor(options) {
		super(options);
		this.protocolOperation = ProtocolOperation.LDAP_RES_MODIFY;
	}
};
//#endregion
//#region src/messages/SearchEntry.ts
var SearchEntry = class extends MessageResponse {
	protocolOperation;
	name;
	attributes;
	constructor(options) {
		super(options);
		this.protocolOperation = ProtocolOperation.LDAP_RES_SEARCH_ENTRY;
		this.name = options.name ?? "";
		this.attributes = options.attributes ?? [];
	}
	parseMessage(reader) {
		this.name = reader.readString() ?? "";
		reader.readSequence();
		const end = reader.offset + reader.length;
		while (reader.offset < end) {
			const attribute = new Attribute();
			attribute.parse(reader);
			this.attributes.push(attribute);
		}
	}
	toObject(requestAttributes, explicitBufferAttributes) {
		const result = { dn: this.name };
		const resultLCAttributes = /* @__PURE__ */ new Set();
		for (const attribute of this.attributes) {
			resultLCAttributes.add(attribute.type.toLocaleLowerCase());
			let { values } = attribute;
			if (explicitBufferAttributes.includes(attribute.type) || values.some((value) => Buffer.isBuffer(value))) values = attribute.parsedBuffers;
			if (values.length) {
				if (values.length === 1) result[attribute.type] = values[0] ?? [];
				else result[attribute.type] = values;
			} else result[attribute.type] = [];
		}
		for (const attribute of requestAttributes) if (typeof result[attribute] === "undefined" && !resultLCAttributes.has(attribute.toLocaleLowerCase())) result[attribute] = [];
		return result;
	}
};
//#endregion
//#region src/messages/SearchReference.ts
var SearchReference = class extends MessageResponse {
	protocolOperation;
	uris;
	constructor(options) {
		super(options);
		this.protocolOperation = ProtocolOperation.LDAP_RES_SEARCH_REF;
		this.uris = options.uris ?? [];
	}
	parseMessage(reader) {
		const end = reader.offset + reader.length;
		while (reader.offset < end) {
			const url = reader.readString() ?? "";
			this.uris.push(url);
		}
	}
};
//#endregion
//#region src/FilterParser.ts
var FilterParser = class FilterParser {
	static parseString(filterString) {
		if (!filterString) throw new Error("Filter cannot be empty");
		if (!filterString.startsWith("(")) filterString = `(${filterString})`;
		const parseResult = FilterParser._parseString(filterString, 0, filterString);
		const end = filterString.length - 1;
		if (parseResult.end < end) throw new Error(`Unbalanced parens in filter string: ${filterString}`);
		return parseResult.filter;
	}
	static parse(reader) {
		const type = reader.readSequence();
		let filter;
		switch (type) {
			case SearchFilter.and:
				filter = new AndFilter({ filters: FilterParser._parseSet(reader) });
				break;
			case SearchFilter.approxMatch:
				filter = new ApproximateFilter();
				filter.parse(reader);
				break;
			case SearchFilter.equalityMatch:
				filter = new EqualityFilter();
				filter.parse(reader);
				break;
			case SearchFilter.extensibleMatch:
				filter = new ExtensibleFilter();
				filter.parse(reader);
				break;
			case SearchFilter.greaterOrEqual:
				filter = new GreaterThanEqualsFilter();
				filter.parse(reader);
				break;
			case SearchFilter.lessOrEqual:
				filter = new LessThanEqualsFilter();
				filter.parse(reader);
				break;
			case SearchFilter.not:
				filter = new NotFilter({ filter: FilterParser.parse(reader) });
				break;
			case SearchFilter.or:
				filter = new OrFilter({ filters: FilterParser._parseSet(reader) });
				break;
			case SearchFilter.present:
				filter = new PresenceFilter();
				filter.parse(reader);
				break;
			case SearchFilter.substrings:
				filter = new SubstringFilter();
				filter.parse(reader);
				break;
			default: throw new Error(`Invalid search filter type: 0x${type ?? "<null>"}`);
		}
		return filter;
	}
	static _parseString(filterString, start, fullString) {
		let cursor = start;
		const { length } = filterString;
		let filter;
		if (filterString[cursor] !== "(") throw new Error(`Missing paren: ${filterString}. Full string: ${fullString}`);
		cursor += 1;
		switch (filterString[cursor]) {
			case "&": {
				cursor += 1;
				const children = [];
				do {
					const childResult = FilterParser._parseString(filterString, cursor, fullString);
					children.push(childResult.filter);
					cursor = childResult.end + 1;
				} while (cursor < length && filterString[cursor] !== ")");
				filter = new AndFilter({ filters: children });
				break;
			}
			case "|": {
				cursor += 1;
				const children = [];
				do {
					const childResult = FilterParser._parseString(filterString, cursor, fullString);
					children.push(childResult.filter);
					cursor = childResult.end + 1;
				} while (cursor < length && filterString[cursor] !== ")");
				filter = new OrFilter({ filters: children });
				break;
			}
			case "!": {
				const childResult = FilterParser._parseString(filterString, cursor + 1, fullString);
				filter = new NotFilter({ filter: childResult.filter });
				cursor = childResult.end + 1;
				break;
			}
			default: {
				const end = filterString.indexOf(")", cursor);
				if (end === -1) throw new Error(`Unbalanced parens: ${filterString}. Full string: ${fullString}`);
				filter = FilterParser._parseExpressionFilterFromString(filterString.substring(cursor, end));
				cursor = end;
			}
		}
		return {
			end: cursor,
			filter
		};
	}
	static _parseExpressionFilterFromString(filterString) {
		let attribute;
		let remainingExpression;
		if (filterString.startsWith(":")) {
			attribute = "";
			remainingExpression = filterString;
		} else {
			const matches = /^[\w-]+/.exec(filterString);
			if (matches?.length) {
				[attribute] = matches;
				remainingExpression = filterString.slice(attribute.length);
			} else throw new Error(`Invalid attribute name: ${filterString}`);
		}
		if (remainingExpression === "=*") return new PresenceFilter({ attribute });
		if (remainingExpression.startsWith("=")) {
			remainingExpression = remainingExpression.slice(1);
			if (remainingExpression.includes("*")) {
				const escapedExpression = FilterParser._unescapeSubstring(remainingExpression);
				return new SubstringFilter({
					attribute,
					initial: escapedExpression.initial,
					any: escapedExpression.any,
					final: escapedExpression.final
				});
			}
			return new EqualityFilter({
				attribute,
				value: FilterParser._unescapeHexValues(remainingExpression)
			});
		}
		if (remainingExpression.startsWith(">") && remainingExpression[1] === "=") return new GreaterThanEqualsFilter({
			attribute,
			value: FilterParser._unescapeHexValues(remainingExpression.slice(2))
		});
		if (remainingExpression.startsWith("<") && remainingExpression[1] === "=") return new LessThanEqualsFilter({
			attribute,
			value: FilterParser._unescapeHexValues(remainingExpression.slice(2))
		});
		if (remainingExpression.startsWith("~") && remainingExpression[1] === "=") return new ApproximateFilter({
			attribute,
			value: FilterParser._unescapeHexValues(remainingExpression.slice(2))
		});
		if (remainingExpression.startsWith(":")) return FilterParser._parseExtensibleFilterFromString(attribute, remainingExpression);
		throw new Error(`Invalid expression: ${filterString}`);
	}
	static _parseExtensibleFilterFromString(attribute, filterString) {
		let dnAttributes = false;
		let rule;
		const fields = filterString.split(":");
		if (fields.length <= 1) throw new Error(`Invalid extensible filter: ${filterString}`);
		fields.shift();
		if (fields[0]?.toLowerCase() === "dn") {
			dnAttributes = true;
			fields.shift();
		}
		if (fields.length && !fields[0]?.startsWith("=")) rule = fields.shift();
		if (fields.length && !fields[0]?.startsWith("=")) throw new Error(`Missing := in extensible filter: ${filterString}`);
		const remainingExpression = fields.join(":").slice(1);
		return new ExtensibleFilter({
			matchType: attribute,
			dnAttributes,
			rule,
			value: FilterParser._unescapeHexValues(remainingExpression)
		});
	}
	static _unescapeHexValues(input) {
		let index = 0;
		const end = input.length;
		let result = "";
		while (index < end) {
			const char = input[index];
			switch (char) {
				case "(": throw new Error(`Illegal unescaped character: ${char} in value: ${input}`);
				case "\\": {
					const value = input.slice(index + 1, index + 3);
					if (/^[\dA-Fa-f]{2}$/.exec(value) === null) throw new Error(`Invalid escaped hex character: ${value} in value: ${input}`);
					result += String.fromCharCode(Number.parseInt(value, 16));
					index += 3;
					break;
				}
				default:
					if (char) result += char;
					index += 1;
			}
		}
		return result;
	}
	static _unescapeSubstring(input) {
		const fields = input.split("*");
		if (fields.length < 2) throw new Error(`Wildcard missing: ${input}`);
		return {
			initial: FilterParser._unescapeHexValues(fields.shift() ?? ""),
			final: FilterParser._unescapeHexValues(fields.pop() ?? ""),
			any: fields.map((field) => FilterParser._unescapeHexValues(field))
		};
	}
	static _parseSet(reader) {
		const filters = [];
		const end = reader.offset + reader.length;
		while (reader.offset < end) filters.push(FilterParser.parse(reader));
		return filters;
	}
};
//#endregion
//#region src/messages/SearchRequest.ts
var SearchRequest = class extends Message {
	protocolOperation;
	baseDN;
	scope;
	derefAliases;
	sizeLimit;
	timeLimit;
	returnAttributeValues;
	filter;
	attributes;
	explicitBufferAttributes;
	constructor(options) {
		super(options);
		this.protocolOperation = ProtocolOperation.LDAP_REQ_SEARCH;
		this.baseDN = options.baseDN ?? "";
		this.scope = options.scope ?? "sub";
		this.derefAliases = options.derefAliases ?? "never";
		this.sizeLimit = options.sizeLimit ?? 0;
		this.timeLimit = options.timeLimit ?? 10;
		this.returnAttributeValues = options.returnAttributeValues !== false;
		this.filter = options.filter;
		this.attributes = options.attributes ?? [];
		this.explicitBufferAttributes = options.explicitBufferAttributes ?? [];
	}
	writeMessage(writer) {
		writer.writeString(this.baseDN);
		switch (this.scope) {
			case "base":
				writer.writeEnumeration(0);
				break;
			case "one":
				writer.writeEnumeration(1);
				break;
			case "sub":
				writer.writeEnumeration(2);
				break;
			case "children":
			case "subordinates":
				writer.writeEnumeration(3);
				break;
			default: throw new Error(`Invalid search scope: ${this.scope}`);
		}
		switch (this.derefAliases) {
			case "never":
				writer.writeEnumeration(0);
				break;
			case "search":
				writer.writeEnumeration(1);
				break;
			case "find":
				writer.writeEnumeration(2);
				break;
			case "always":
				writer.writeEnumeration(3);
				break;
			default: throw new Error(`Invalid deref alias: ${this.derefAliases}`);
		}
		writer.writeInt(this.sizeLimit);
		writer.writeInt(this.timeLimit);
		writer.writeBoolean(!this.returnAttributeValues);
		this.filter.write(writer);
		writer.startSequence();
		for (const attribute of this.attributes) writer.writeString(attribute);
		writer.endSequence();
	}
	parseMessage(reader) {
		this.baseDN = reader.readString() ?? "";
		const scope = reader.readEnumeration();
		switch (scope) {
			case 0:
				this.scope = "base";
				break;
			case 1:
				this.scope = "one";
				break;
			case 2:
				this.scope = "sub";
				break;
			case 3:
				this.scope = "children";
				break;
			default: throw new Error(`Invalid search scope: ${scope ?? "<null>"}`);
		}
		const derefAliases = reader.readEnumeration();
		switch (scope) {
			case 0:
				this.derefAliases = "never";
				break;
			case 1:
				this.derefAliases = "search";
				break;
			case 2:
				this.derefAliases = "find";
				break;
			case 3:
				this.derefAliases = "always";
				break;
			default: throw new Error(`Invalid deref alias: ${derefAliases ?? "<null>"}`);
		}
		this.sizeLimit = reader.readInt() ?? 0;
		this.timeLimit = reader.readInt() ?? 0;
		this.returnAttributeValues = !(reader.readBoolean() ?? false);
		this.filter = FilterParser.parse(reader);
		if (reader.peek() === 48) {
			reader.readSequence();
			const end = reader.offset + reader.length;
			while (reader.offset < end) this.attributes.push((reader.readString() ?? "").toLowerCase());
		}
	}
};
//#endregion
//#region src/messages/SearchResponse.ts
var SearchResponse = class extends MessageResponse {
	protocolOperation;
	searchEntries;
	searchReferences;
	constructor(options) {
		super(options);
		this.protocolOperation = ProtocolOperation.LDAP_RES_SEARCH;
		this.searchEntries = options.searchEntries ?? [];
		this.searchReferences = options.searchReferences ?? [];
	}
};
//#endregion
//#region src/messages/UnbindRequest.ts
var UnbindRequest = class extends Message {
	protocolOperation;
	constructor(options) {
		super(options);
		this.protocolOperation = ProtocolOperation.LDAP_REQ_UNBIND;
	}
};
//#endregion
//#region src/MessageParser.ts
const TypedEventEmitter = node_events.EventEmitter;
var MessageParser = class extends TypedEventEmitter {
	buffer;
	read(data, messageDetailsByMessageId) {
		let nextMessage;
		if (this.buffer) this.buffer = Buffer.concat([this.buffer, data]);
		else this.buffer = data;
		const reader = new BerReader(this.buffer);
		let foundSequence = null;
		try {
			foundSequence = reader.readSequence();
		} catch (ex) {
			this.emit("error", ex);
		}
		if (!foundSequence || reader.remain < reader.length) return;
		if (reader.remain > reader.length) {
			nextMessage = this.buffer.subarray(reader.offset + reader.length);
			reader.setBufferSize(reader.offset + reader.length);
		}
		delete this.buffer;
		let messageId;
		let protocolOperation;
		try {
			messageId = reader.readInt();
			if (messageId == null) throw new Error(`Unable to read message id`);
			protocolOperation = reader.readSequence();
			if (protocolOperation == null) throw new Error(`Unable to read protocol operation sequence for message: ${messageId}`);
			const messageDetails = messageDetailsByMessageId.get(`${messageId}`);
			const message = this._getMessageFromProtocolOperation(messageId, protocolOperation, reader, messageDetails?.message);
			this.emit("message", message);
		} catch (ex) {
			if (messageId) {
				const errorWithMessageDetails = ex;
				errorWithMessageDetails.messageDetails = { messageId };
				if (protocolOperation) errorWithMessageDetails.messageDetails.protocolOperation = protocolOperation;
				this.emit("error", errorWithMessageDetails);
				return;
			}
			this.emit("error", ex);
			return;
		}
		if (nextMessage) this.read(nextMessage, messageDetailsByMessageId);
	}
	_getMessageFromProtocolOperation(messageId, protocolOperation, reader, messageDetails) {
		let message;
		switch (protocolOperation) {
			case ProtocolOperation.LDAP_RES_BIND:
				message = new BindResponse({ messageId });
				break;
			case ProtocolOperation.LDAP_RES_ADD:
				message = new AddResponse({ messageId });
				break;
			case ProtocolOperation.LDAP_RES_COMPARE:
				message = new CompareResponse({ messageId });
				break;
			case ProtocolOperation.LDAP_RES_DELETE:
				message = new DeleteResponse({ messageId });
				break;
			case ProtocolOperation.LDAP_RES_EXTENSION:
				message = new ExtendedResponse({ messageId });
				break;
			case ProtocolOperation.LDAP_RES_MODRDN:
				message = new ModifyDNResponse({ messageId });
				break;
			case ProtocolOperation.LDAP_RES_MODIFY:
				message = new ModifyResponse({ messageId });
				break;
			case ProtocolOperation.LDAP_RES_SEARCH:
				message = new SearchResponse({ messageId });
				break;
			case ProtocolOperation.LDAP_RES_SEARCH_ENTRY:
				message = new SearchEntry({ messageId });
				break;
			case ProtocolOperation.LDAP_RES_SEARCH_REF:
				message = new SearchReference({ messageId });
				break;
			default: {
				const error = new MessageParserError(`Protocol Operation not supported: 0x${protocolOperation.toString(16)}`);
				error.messageDetails = {
					messageId,
					protocolOperation
				};
				throw error;
			}
		}
		message.parse(reader, messageDetails?.controls ?? []);
		return message;
	}
};
//#endregion
//#region src/MessageResponseStatus.ts
const MessageResponseStatus = {
	Success: 0,
	SizeLimitExceeded: 4
};
//#endregion
//#region src/StatusCodeParser.ts
var StatusCodeParser = class {
	static parse(result) {
		if (!result) return new NoResultError();
		switch (result.status) {
			case 1: return new OperationsError(result.errorMessage);
			case 2: return new ProtocolError(result.errorMessage);
			case 3: return new TimeLimitExceededError(result.errorMessage);
			case 4: return new SizeLimitExceededError(result.errorMessage);
			case 7: return new AuthMethodNotSupportedError(result.errorMessage);
			case 8: return new StrongAuthRequiredError(result.errorMessage);
			case 11: return new AdminLimitExceededError(result.errorMessage);
			case 12: return new UnavailableCriticalExtensionError(result.errorMessage);
			case 13: return new ConfidentialityRequiredError(result.errorMessage);
			case 14: return new SaslBindInProgressError(result);
			case 16: return new NoSuchAttributeError(result.errorMessage);
			case 17: return new UndefinedTypeError(result.errorMessage);
			case 18: return new InappropriateMatchingError(result.errorMessage);
			case 19: return new ConstraintViolationError(result.errorMessage);
			case 20: return new TypeOrValueExistsError(result.errorMessage);
			case 21: return new InvalidSyntaxError(result.errorMessage);
			case 32: return new NoSuchObjectError(result.errorMessage);
			case 33: return new AliasProblemError(result.errorMessage);
			case 34: return new InvalidDNSyntaxError(result.errorMessage);
			case 35: return new IsLeafError(result.errorMessage);
			case 36: return new AliasDerefProblemError(result.errorMessage);
			case 48: return new InappropriateAuthError(result.errorMessage);
			case 49: return new InvalidCredentialsError(result.errorMessage);
			case 50: return new InsufficientAccessError(result.errorMessage);
			case 51: return new BusyError(result.errorMessage);
			case 52: return new UnavailableError(result.errorMessage);
			case 53: return new UnwillingToPerformError(result.errorMessage);
			case 54: return new LoopDetectError(result.errorMessage);
			case 64: return new NamingViolationError(result.errorMessage);
			case 65: return new ObjectClassViolationError(result.errorMessage);
			case 66: return new NotAllowedOnNonLeafError(result.errorMessage);
			case 67: return new NotAllowedOnRDNError(result.errorMessage);
			case 68: return new AlreadyExistsError(result.errorMessage);
			case 69: return new NoObjectClassModsError(result.errorMessage);
			case 70: return new ResultsTooLargeError(result.errorMessage);
			case 71: return new AffectsMultipleDSAsError(result.errorMessage);
			case 95: return new MoreResultsToReturnError(result.errorMessage);
			case 112: return new TLSNotSupportedError(result.errorMessage);
			case 248: return new NoResultError(result.errorMessage);
			default: return new UnknownStatusCodeError(result.status, result.errorMessage);
		}
	}
};
//#endregion
//#region src/Client.ts
const MAX_MESSAGE_ID = 2 ** 31 - 1;
const logDebug = (0, node_util.debuglog)("ldapts");
var Client = class {
	clientOptions;
	messageId = 1;
	host;
	port;
	secure;
	connected = false;
	bound = false;
	startTLSUpgraded = false;
	rebind;
	socket;
	connectTimer;
	messageParser = new MessageParser();
	messageDetailsByMessageId = /* @__PURE__ */ new Map();
	constructor(options) {
		this.clientOptions = options;
		this.clientOptions.timeout ??= 0;
		this.clientOptions.connectTimeout ??= 0;
		this.clientOptions.strictDN = this.clientOptions.strictDN !== false;
		let parsedUrl;
		try {
			parsedUrl = new URL(options.url);
		} catch {
			throw new Error(`${options.url} is an invalid LDAP URL (protocol)`);
		}
		const scheme = parsedUrl.protocol.replace(/:$/, "");
		if (scheme !== "ldap" && scheme !== "ldaps") throw new Error(`${options.url} is an invalid LDAP URL (protocol)`);
		const isSecureProtocol = scheme === "ldaps";
		const hasTlsOptions = !!this.clientOptions.tlsOptions && Object.values(this.clientOptions.tlsOptions).some((value) => value !== void 0);
		this.secure = isSecureProtocol || hasTlsOptions;
		let host = parsedUrl.hostname;
		if (host.startsWith("[") && host.endsWith("]")) host = host.slice(1, -1);
		this.host = host || "localhost";
		if (parsedUrl.port) this.port = Number(parsedUrl.port);
		else if (isSecureProtocol) this.port = 636;
		else this.port = 389;
		this.messageParser.on("error", (err) => {
			if (err.messageDetails?.messageId) {
				const messageDetails = this.messageDetailsByMessageId.get(err.messageDetails.messageId.toString());
				if (messageDetails) {
					this.messageDetailsByMessageId.delete(err.messageDetails.messageId.toString());
					messageDetails.reject(err);
					return;
				}
			}
			if (err.stack) logDebug(err.stack);
		});
		this.messageParser.on("message", this._handleSendResponse.bind(this));
	}
	get isConnected() {
		return !!this.socket && this.connected;
	}
	/**
	* True when the current connection has successfully bound. Becomes false when the connection
	* is closed or re-established, which makes it possible to detect a connection that was
	* transparently reconnected but is no longer authenticated.
	* @returns {boolean} True if the current connection is authenticated
	*/
	get isBound() {
		return this.isConnected && this.bound;
	}
	async startTLS(options = {}, controls) {
		if (!this.isConnected) await this._connect();
		await this.exop("1.3.6.1.4.1.1466.20037", void 0, controls);
		const originalSocket = this.socket;
		if (originalSocket) {
			originalSocket.removeListener("data", this.socketDataHandler);
			options.socket = originalSocket;
		}
		this.socket = await new Promise((resolve, reject) => {
			const secureSocket = (this.clientOptions.createSecureConnection ?? node_tls.connect)(options);
			secureSocket.once("secureConnect", () => {
				secureSocket.removeAllListeners("error");
				secureSocket.on("data", this.socketDataHandler);
				secureSocket.on("error", () => {
					if (originalSocket) originalSocket.destroy();
				});
				resolve(secureSocket);
			});
			secureSocket.once("error", (err) => {
				secureSocket.removeAllListeners();
				reject(err);
			});
		});
		if (originalSocket) this.socket.id = originalSocket.id;
		this.startTLSUpgraded = true;
	}
	/**
	* Performs a simple or sasl authentication against the server.
	* @param {string|DN|SaslMechanism} dnOrSaslMechanism
	* @param {string} [password]
	* @param {Control|Control[]} [controls]
	*/
	async bind(dnOrSaslMechanism, password, controls) {
		if (controls && !Array.isArray(controls)) controls = [controls];
		if (typeof dnOrSaslMechanism === "string" && SASL_MECHANISMS.includes(dnOrSaslMechanism)) {
			await this.bindSASL(dnOrSaslMechanism, password, controls);
			return;
		}
		const req = new BindRequest({
			messageId: this._nextMessageId(),
			dn: typeof dnOrSaslMechanism === "string" ? dnOrSaslMechanism : dnOrSaslMechanism.toString(),
			password,
			controls
		});
		await this._sendBind(req);
		this._onBindSuccess(() => this.bind(dnOrSaslMechanism, password, controls));
	}
	/**
	* Performs a sasl authentication against the server.
	* @param {string|SaslMechanism} mechanism
	* @param {string} [password]
	* @param {Control|Control[]} [controls]
	*/
	async bindSASL(mechanism, password, controls) {
		if (controls && !Array.isArray(controls)) controls = [controls];
		const req = new BindRequest({
			messageId: this._nextMessageId(),
			mechanism,
			password,
			controls
		});
		await this._sendBind(req);
		this._onBindSuccess(() => this.bindSASL(mechanism, password, controls));
	}
	/**
	* Used to create a new entry in the directory
	* @param {string|DN} dn - The DN of the entry to add
	* @param {Attribute[]|object} attributes - Array of attributes or object where keys are the name of each attribute
	* @param {Control|Control[]} [controls]
	*/
	async add(dn, attributes, controls) {
		await this._ensureConnected();
		if (controls && !Array.isArray(controls)) controls = [controls];
		let attributesToAdd;
		if (Array.isArray(attributes)) attributesToAdd = attributes;
		else {
			attributesToAdd = [];
			for (const [key, value] of Object.entries(attributes)) {
				let values;
				if (Array.isArray(value)) values = value;
				else if (value == null) values = [];
				else values = [value];
				attributesToAdd.push(new Attribute({
					type: key,
					values
				}));
			}
		}
		const req = new AddRequest({
			messageId: this._nextMessageId(),
			dn: typeof dn === "string" ? dn : dn.toString(),
			attributes: attributesToAdd,
			controls
		});
		const result = await this._send(req);
		if (result?.status !== MessageResponseStatus.Success) throw StatusCodeParser.parse(result);
	}
	/**
	* Compares an attribute/value pair with an entry on the LDAP server.
	* @param {string|DN} dn - The DN of the entry to compare attributes with
	* @param {string} attribute
	* @param {string} value
	* @param {Control|Control[]} [controls]
	* @returns true if attribute and value match; otherwise false
	*/
	async compare(dn, attribute, value, controls) {
		await this._ensureConnected();
		if (controls && !Array.isArray(controls)) controls = [controls];
		const req = new CompareRequest({
			messageId: this._nextMessageId(),
			dn: typeof dn === "string" ? dn : dn.toString(),
			attribute,
			value,
			controls
		});
		const response = await this._send(req);
		switch (response?.status) {
			case 6: return true;
			case 5: return false;
			default: throw StatusCodeParser.parse(response);
		}
	}
	/**
	* Deletes an entry from the LDAP server.
	* @param {string|DN} dn - The DN of the entry to delete
	* @param {Control|Control[]} [controls]
	*/
	async del(dn, controls) {
		await this._ensureConnected();
		if (controls && !Array.isArray(controls)) controls = [controls];
		const req = new DeleteRequest({
			messageId: this._nextMessageId(),
			dn: typeof dn === "string" ? dn : dn.toString(),
			controls
		});
		const result = await this._send(req);
		if (result?.status !== MessageResponseStatus.Success) throw StatusCodeParser.parse(result);
	}
	/**
	* Performs an extended operation on the LDAP server.
	* @param {string} oid - The object identifier (OID) of the extended operation to perform
	* @param {string|Buffer} [value]
	* @param {Control|Control[]} [controls]
	* @returns exop result
	*/
	async exop(oid, value, controls) {
		await this._ensureConnected();
		if (controls && !Array.isArray(controls)) controls = [controls];
		const req = new ExtendedRequest({
			messageId: this._nextMessageId(),
			oid,
			value,
			controls
		});
		const result = await this._send(req);
		if (result?.status !== MessageResponseStatus.Success) throw StatusCodeParser.parse(result);
		return {
			oid: result.oid,
			value: result.value
		};
	}
	/**
	* Performs an LDAP modify against the server.
	* @param {string|DN} dn - The DN of the entry to modify
	* @param {Change|Change[]} changes
	* @param {Control|Control[]} [controls]
	*/
	async modify(dn, changes, controls) {
		await this._ensureConnected();
		if (!Array.isArray(changes)) changes = [changes];
		if (controls && !Array.isArray(controls)) controls = [controls];
		const req = new ModifyRequest({
			messageId: this._nextMessageId(),
			dn: typeof dn === "string" ? dn : dn.toString(),
			changes,
			controls
		});
		const result = await this._send(req);
		if (result?.status !== MessageResponseStatus.Success) throw StatusCodeParser.parse(result);
	}
	/**
	* Performs an LDAP modifyDN against the server.
	* @param {string|DN} dn - The DN of the entry to modify
	* @param {string|DN} newDN - The new DN to move this entry to
	* @param {Control|Control[]} [controls]
	*/
	async modifyDN(dn, newDN, controls) {
		await this._ensureConnected();
		if (controls && !Array.isArray(controls)) controls = [controls];
		let newSuperior;
		if (typeof newDN === "string" && /[^\\],/.test(newDN)) {
			const parseIndex = newDN.search(/[^\\],/);
			newSuperior = newDN.slice(parseIndex + 2);
			newDN = newDN.slice(0, parseIndex + 1);
		}
		const req = new ModifyDNRequest({
			messageId: this._nextMessageId(),
			dn: typeof dn === "string" ? dn : dn.toString(),
			deleteOldRdn: true,
			newRdn: typeof newDN === "string" ? newDN : newDN.toString(),
			newSuperior,
			controls
		});
		const result = await this._send(req);
		if (result?.status !== MessageResponseStatus.Success) throw StatusCodeParser.parse(result);
	}
	/**
	* Performs an LDAP search against the server.
	* @param {string|DN} baseDN - This specifies the base of the subtree in which the search is to be constrained.
	* @param {SearchOptions} [options]
	* @param {string|Filter} [options.filter] - The filter of the search request. It must conform to the LDAP filter syntax specified in RFC4515. Defaults to (objectclass=*)
	* @param {string} [options.scope] - Specifies how broad the search context is:
	* - base - Indicates that only the entry specified as the search base should be considered. None of its subordinates will be considered.
	* - one - Indicates that only the immediate children of the entry specified as the search base should be considered. The base entry itself should not be considered, nor any descendants of the immediate children of the base entry.
	* - sub - Indicates that the entry specified as the search base, and all of its subordinates to any depth, should be considered.
	* - children or subordinates - Indicates that the entry specified by the search base should not be considered, but all of its subordinates to any depth should be considered.
	* @param {string} [options.derefAliases] - Specifies how the server must treat references to other entries:
	* - never - Never dereferences entries, returns alias objects instead. The alias contains the reference to the real entry.
	* - always - Always returns the referenced entries, not the alias object.
	* - search - While searching subordinates of the base object, dereferences any alias within the search scope. Dereferenced objects become the bases of further search scopes where the Search operation is also applied by the server. The server should eliminate duplicate entries that arise due to alias dereferencing while searching.
	* - find - Dereferences aliases in locating the base object of the search, but not when searching subordinates of the base object.
	* @param {boolean} [options.returnAttributeValues] - If true, attribute values should be included in the entries that are returned; otherwise entries that match the search criteria should be returned containing only the attribute descriptions for the attributes contained in that entry but should not include the values for those attributes.
	* @param {number} [options.sizeLimit] - This specifies the maximum number of entries that should be returned from the search. A value of zero indicates no limit. Note that the server may also impose a size limit for the search operation, and in that case the smaller of the client-requested and server-imposed size limits will be enforced.
	* @param {number} [options.timeLimit] - This specifies the maximum length of time, in seconds, that the server should spend processing the search. A value of zero indicates no limit. Note that the server may also impose a time limit for the search operation, and in that case the smaller of the client-requested and server-imposed time limits will be enforced.
	* @param {boolean|SearchPageOptions} [options.paged] - Used to allow paging and specify the page size
	* @param {string[]} [options.attributes] - A set of attributes to request for inclusion in entries that match the search criteria and are returned to the client. If a specific set of attribute descriptions are listed, then only those attributes should be included in matching entries. The special value “*” indicates that all user attributes should be included in matching entries. The special value “+” indicates that all operational attributes should be included in matching entries. The special value “1.1” indicates that no attributes should be included in matching entries. Some servers may also support the ability to use the “@” symbol followed by an object class name (e.g., “@inetOrgPerson”) to request all attributes associated with that object class. If the set of attributes to request is empty, then the server should behave as if the value “*” was specified to request that all user attributes be included in entries that are returned.
	* @param {string[]} [options.explicitBufferAttributes] - List of attributes to explicitly return as buffers
	* @param {Control|Control[]} [controls]
	* @returns {Promise<SearchResult>}
	*/
	async search(baseDN, options = {}, controls) {
		await this._ensureConnected();
		if (controls) {
			if (Array.isArray(controls)) controls = controls.slice(0);
			else controls = [controls];
			for (const control of controls) if (control instanceof PagedResultsControl) throw new Error("Should not specify PagedResultsControl");
		} else controls = [];
		let pageSize = 100;
		if (typeof options.paged === "object" && options.paged.pageSize) pageSize = options.paged.pageSize;
		else if (options.sizeLimit && options.sizeLimit > 1) pageSize = options.sizeLimit - 1;
		let pagedResultsControl;
		const shouldPage = !!options.paged;
		if (shouldPage) {
			pagedResultsControl = new PagedResultsControl({ value: { size: pageSize } });
			controls.push(pagedResultsControl);
		}
		let filter;
		if (options.filter) {
			if (typeof options.filter === "string") filter = FilterParser.parseString(options.filter);
			else filter = options.filter;
		} else filter = new PresenceFilter({ attribute: "objectclass" });
		const searchRequest = new SearchRequest({
			messageId: -1,
			baseDN: typeof baseDN === "string" ? baseDN : baseDN.toString(),
			scope: options.scope,
			filter,
			attributes: options.attributes,
			explicitBufferAttributes: options.explicitBufferAttributes,
			returnAttributeValues: options.returnAttributeValues,
			sizeLimit: options.sizeLimit,
			timeLimit: options.timeLimit,
			controls
		});
		const searchResult = {
			searchEntries: [],
			searchReferences: []
		};
		await this._sendSearch(searchRequest, searchResult, shouldPage, pageSize, pagedResultsControl);
		return searchResult;
	}
	async *searchPaginated(baseDN, options = {}, controls) {
		await this._ensureConnected();
		if (controls) {
			if (Array.isArray(controls)) controls = controls.slice(0);
			else controls = [controls];
			for (const control of controls) if (control instanceof PagedResultsControl) throw new Error("Should not specify PagedResultsControl");
		} else controls = [];
		let pageSize = 100;
		if (typeof options.paged === "object" && options.paged.pageSize) pageSize = options.paged.pageSize;
		else if (options.sizeLimit && options.sizeLimit > 1) pageSize = options.sizeLimit - 1;
		let pagedResultsControl;
		pagedResultsControl = new PagedResultsControl({ value: { size: pageSize } });
		controls.push(pagedResultsControl);
		let filter;
		if (options.filter) {
			if (typeof options.filter === "string") filter = FilterParser.parseString(options.filter);
			else filter = options.filter;
		} else filter = new PresenceFilter({ attribute: "objectclass" });
		const searchRequest = new SearchRequest({
			messageId: -1,
			baseDN: typeof baseDN === "string" ? baseDN : baseDN.toString(),
			scope: options.scope,
			filter,
			attributes: options.attributes,
			explicitBufferAttributes: options.explicitBufferAttributes,
			returnAttributeValues: options.returnAttributeValues,
			sizeLimit: options.sizeLimit,
			timeLimit: options.timeLimit,
			controls
		});
		do {
			const searchResult = {
				searchEntries: [],
				searchReferences: []
			};
			pagedResultsControl = await this._sendSearch(searchRequest, searchResult, true, pageSize, pagedResultsControl, false);
			yield searchResult;
		} while (pagedResultsControl);
	}
	/**
	* Unbinds this client from the LDAP server.
	* @returns {void|Promise} void if not connected; otherwise returns a promise to the request to disconnect
	*/
	async unbind() {
		try {
			this.rebind = void 0;
			if (!this.connected || !this.socket) return;
			const req = new UnbindRequest({ messageId: this._nextMessageId() });
			await this._send(req);
		} finally {
			this._destroySocket(this.socket);
		}
	}
	[Symbol.asyncDispose]() {
		return this.unbind();
	}
	async _sendBind(req) {
		if (!this.isConnected) await this._connect();
		const result = await this._send(req);
		if (result?.status !== MessageResponseStatus.Success) throw StatusCodeParser.parse(result);
	}
	async _sendSearch(searchRequest, searchResult, paged, pageSize, pagedResultsControl, fetchAll = true) {
		searchRequest.messageId = this._nextMessageId();
		const result = await this._send(searchRequest);
		if (result?.status !== MessageResponseStatus.Success && !(result?.status === MessageResponseStatus.SizeLimitExceeded && searchRequest.sizeLimit)) throw StatusCodeParser.parse(result);
		for (const searchEntry of result.searchEntries) searchResult.searchEntries.push(searchEntry.toObject(searchRequest.attributes, searchRequest.explicitBufferAttributes));
		for (const searchReference of result.searchReferences) searchResult.searchReferences.push(...searchReference.uris);
		if (paged && (result.searchEntries.length || result.searchReferences.length) && pagedResultsControl) {
			let pagedResultsFromResponse;
			for (const control of result.controls ?? []) if (control instanceof PagedResultsControl) {
				pagedResultsFromResponse = control;
				break;
			}
			if (pagedResultsFromResponse?.value?.cookie?.length) {
				pagedResultsControl.value = pagedResultsControl.value ?? { size: pageSize };
				pagedResultsControl.value.cookie = pagedResultsFromResponse.value.cookie;
				if (fetchAll) await this._sendSearch(searchRequest, searchResult, paged, pageSize, pagedResultsControl, true);
				else return pagedResultsControl;
			}
		}
	}
	socketDataHandler = (data) => {
		if (this.messageParser) this.messageParser.read(data, this.messageDetailsByMessageId);
	};
	_nextMessageId() {
		this.messageId += 1;
		if (this.messageId >= MAX_MESSAGE_ID) this.messageId = 1;
		return this.messageId;
	}
	/**
	* Records a successful bind and, when autoRebind is enabled, remembers how to replay it after
	* a transparent reconnect. Binds on a startTLS-upgraded session are not replayed: the rebind
	* happens before the fresh connection could be upgraded again, so replaying would downgrade
	* the security of the credentials.
	* @param {Function} rebind - Replays the bind that just succeeded
	* @private
	*/
	_onBindSuccess(rebind) {
		this.bound = true;
		if (this.clientOptions.autoRebind && !this.startTLSUpgraded) this.rebind = rebind;
	}
	/**
	* Ensures the socket connection is established and, when autoRebind is enabled, replays the
	* last successful bind on a freshly re-established connection.
	* @returns {Promise<void>}
	* @private
	*/
	async _ensureConnected() {
		if (this.isConnected) return;
		await this._connect();
		if (this.rebind && !this.bound) await this.rebind();
	}
	/**
	* Open the socket connection
	* @returns {Promise<void>|void}
	* @private
	*/
	_connect() {
		if (this.isConnected) return;
		return new Promise((resolve, reject) => {
			if (this.secure) {
				const createSecureConnection = this.clientOptions.createSecureConnection ?? node_tls.connect;
				this.socket = createSecureConnection(this.port, this.host, this.clientOptions.tlsOptions);
				this.socket.id = node_crypto.randomUUID();
				this.socket.once("secureConnect", () => {
					this._onConnect(resolve);
				});
			} else {
				const createConnection = this.clientOptions.createConnection ?? node_net.connect;
				this.socket = createConnection(this.port, this.host);
				this.socket.id = node_crypto.randomUUID();
				this.socket.once("connect", () => {
					this._onConnect(resolve);
				});
			}
			this.socket.once("error", (err) => {
				this._destroySocket(this.socket);
				reject(err);
			});
			if (!this.socket.connecting && this.socket.readyState === "open") {
				this._onConnect(resolve);
				return;
			}
			if (this.clientOptions.connectTimeout) this.connectTimer = setTimeout(() => {
				this._destroySocket(this.socket);
				reject(/* @__PURE__ */ new Error("Connection timeout"));
			}, this.clientOptions.connectTimeout);
		});
	}
	_onConnect(next) {
		if (this.connectTimer) {
			clearTimeout(this.connectTimer);
			this.connectTimer = void 0;
		}
		if (this.socket) {
			this.socket.removeAllListeners("error");
			this.socket.removeAllListeners("connect");
			this.socket.removeAllListeners("secureConnect");
		}
		this.connected = true;
		const socketError = (err) => {
			for (const [key, messageDetails] of this.messageDetailsByMessageId.entries()) {
				if (messageDetails.message instanceof UnbindRequest) messageDetails.resolve();
				else messageDetails.reject(/* @__PURE__ */ new Error(`Socket error. Message type: ${messageDetails.message.constructor.name} (0x${messageDetails.message.protocolOperation.toString(16)})\n${err.message || (err.stack ?? "Unknown socket error")}`));
				this.messageDetailsByMessageId.delete(key);
			}
			if (this.socket) this.socket.destroy();
		};
		function socketEnd() {
			if (this) this.end();
		}
		function socketTimeout() {
			if (this) this.end();
		}
		const clientInstance = this;
		function socketClose() {
			if (this) {
				this.removeListener("error", socketError);
				this.removeListener("close", socketClose);
				this.removeListener("data", clientInstance.socketDataHandler);
				this.removeListener("end", socketEnd);
				this.removeListener("timeout", socketTimeout);
			}
			if (this === clientInstance.socket) {
				clientInstance.connected = false;
				clientInstance.bound = false;
				clientInstance.startTLSUpgraded = false;
				delete clientInstance.socket;
				if (clientInstance.connectTimer) {
					clearTimeout(clientInstance.connectTimer);
					clientInstance.connectTimer = void 0;
				}
			}
			for (const [key, messageDetails] of clientInstance.messageDetailsByMessageId.entries()) if (messageDetails.socket.id === this.id) {
				if (messageDetails.message instanceof UnbindRequest) messageDetails.resolve();
				else messageDetails.reject(/* @__PURE__ */ new Error(`Connection closed before message response was received. Message type: ${messageDetails.message.constructor.name} (0x${messageDetails.message.protocolOperation.toString(16)})`));
				clientInstance.messageDetailsByMessageId.delete(key);
			}
		}
		if (this.socket) {
			this.socket.on("error", socketError);
			this.socket.on("close", socketClose);
			this.socket.on("data", this.socketDataHandler);
			this.socket.on("end", socketEnd);
			this.socket.on("timeout", socketTimeout);
		}
		next();
	}
	_destroySocket(socket) {
		if (socket) {
			if (this.connectTimer) {
				clearTimeout(this.connectTimer);
				this.connectTimer = void 0;
			}
			socket.removeAllListeners("error");
			socket.on("error", () => {});
			socket.end();
			socket.destroy();
			if (socket === this.socket) {
				this.connected = false;
				this.bound = false;
				this.startTLSUpgraded = false;
				this.socket = void 0;
			}
		}
	}
	/**
	* Sends request message to the ldap server over the connected socket. Each message request is given a
	* unique id (messageId), used to identify the associated response when it is sent back over the socket.
	* @returns {Promise<Message>}
	* @private
	* @param {object} message
	*/
	_send(message) {
		if (!this.connected || !this.socket) throw new Error("Socket connection not established");
		const messageContentBuffer = message.write();
		let messageResolve = () => {};
		let messageReject = () => {};
		const messageTimeoutId = this.clientOptions.timeout ? setTimeout(() => {
			const messageDetails = this.messageDetailsByMessageId.get(message.messageId.toString());
			if (messageDetails) {
				this._destroySocket(messageDetails.socket);
				messageReject(/* @__PURE__ */ new Error(`${message.constructor.name}: Operation timed out`));
			}
		}, this.clientOptions.timeout) : null;
		const sendPromise = new Promise((resolve, reject) => {
			messageResolve = resolve;
			messageReject = reject;
		}).finally(() => {
			if (messageTimeoutId) clearTimeout(messageTimeoutId);
		});
		this.messageDetailsByMessageId.set(message.messageId.toString(), {
			message,
			resolve: messageResolve,
			reject: messageReject,
			timeoutTimer: messageTimeoutId,
			socket: this.socket
		});
		if (message.password) logDebug(`Sending message: ${JSON.stringify({
			...message,
			password: "__redacted__"
		})}`);
		else logDebug(`Sending message: ${JSON.stringify(message)}`);
		this.socket.write(messageContentBuffer, () => {
			if (message instanceof AbandonRequest) {
				logDebug(`Abandoned message: ${message.messageId}`);
				this.messageDetailsByMessageId.delete(message.messageId.toString());
				messageResolve();
			} else if (message instanceof UnbindRequest) {
				logDebug("Unbind success. Ending socket");
				if (this.socket) this._destroySocket(this.socket);
			} else logDebug("Message sent successfully.");
		});
		return sendPromise;
	}
	_handleSendResponse(message) {
		const messageDetails = this.messageDetailsByMessageId.get(message.messageId.toString());
		if (messageDetails) {
			if (message instanceof SearchEntry) {
				messageDetails.searchEntries = messageDetails.searchEntries ?? [];
				messageDetails.searchEntries.push(message);
			} else if (message instanceof SearchReference) {
				messageDetails.searchReferences = messageDetails.searchReferences ?? [];
				messageDetails.searchReferences.push(message);
			} else if (message instanceof SearchResponse) {
				if (messageDetails.searchEntries) message.searchEntries.push(...messageDetails.searchEntries);
				if (messageDetails.searchReferences) message.searchReferences.push(...messageDetails.searchReferences);
				this.messageDetailsByMessageId.delete(message.messageId.toString());
				messageDetails.resolve(message);
			} else {
				this.messageDetailsByMessageId.delete(message.messageId.toString());
				messageDetails.resolve(message);
			}
		} else logDebug(`Unable to find details related to message response: ${JSON.stringify(message)}`);
	}
};
//#endregion
//#region src/PostalAddress.ts
/**
* Encodes a postal address string into RFC 4517 Postal Address Syntax.
* @param {string} address - The address with lines separated by the separator
* @param {string} separator - Line separator in the input (default: '\n')
* @returns {string} Encoded postal address string
*/
function encodePostalAddress(address, separator = "\n") {
	return address.split(separator).map((line) => line.replaceAll("\\", "\\5C").replaceAll("$", "\\24")).join("$");
}
/**
* Decodes an RFC 4517 Postal Address Syntax string into a postal address.
* @param {string} encoded - The RFC 4517 encoded postal address
* @param {string} separator - Line separator for the output (default: '\n')
* @returns {string} Decoded postal address string
*/
function decodePostalAddress(encoded, separator = "\n") {
	return encoded.split("$").map((line) => line.replace(/\\(5c|24)/gi, (_, code) => code === "24" ? "$" : "\\")).join(separator);
}
//#endregion
exports.AbandonRequest = AbandonRequest;
exports.AddRequest = AddRequest;
exports.AddResponse = AddResponse;
exports.AdminLimitExceededError = AdminLimitExceededError;
exports.AffectsMultipleDSAsError = AffectsMultipleDSAsError;
exports.AliasDerefProblemError = AliasDerefProblemError;
exports.AliasProblemError = AliasProblemError;
exports.AlreadyExistsError = AlreadyExistsError;
exports.AndFilter = AndFilter;
exports.ApproximateFilter = ApproximateFilter;
exports.Attribute = Attribute;
exports.AuthMethodNotSupportedError = AuthMethodNotSupportedError;
exports.Ber = Ber;
exports.BerReader = BerReader;
exports.BerWriter = BerWriter;
exports.BindRequest = BindRequest;
exports.BindResponse = BindResponse;
exports.BusyError = BusyError;
exports.Change = Change;
exports.Client = Client;
exports.CompareRequest = CompareRequest;
exports.CompareResponse = CompareResponse;
exports.CompareResult = CompareResult;
exports.ConfidentialityRequiredError = ConfidentialityRequiredError;
exports.ConstraintViolationError = ConstraintViolationError;
exports.Control = Control;
exports.ControlParser = ControlParser;
exports.DN = DN;
exports.DeleteRequest = DeleteRequest;
exports.DeleteResponse = DeleteResponse;
exports.EntryChangeNotificationControl = EntryChangeNotificationControl;
exports.EqualityFilter = EqualityFilter;
exports.ExtendedRequest = ExtendedRequest;
exports.ExtendedResponse = ExtendedResponse;
exports.ExtendedResponseProtocolOperations = ExtendedResponseProtocolOperations;
exports.ExtensibleFilter = ExtensibleFilter;
exports.Filter = Filter;
exports.FilterParser = FilterParser;
exports.GreaterThanEqualsFilter = GreaterThanEqualsFilter;
exports.InappropriateAuthError = InappropriateAuthError;
exports.InappropriateMatchingError = InappropriateMatchingError;
exports.InsufficientAccessError = InsufficientAccessError;
exports.InvalidAsn1Error = InvalidAsn1Error;
exports.InvalidCredentialsError = InvalidCredentialsError;
exports.InvalidDNSyntaxError = InvalidDNSyntaxError;
exports.InvalidSyntaxError = InvalidSyntaxError;
exports.IsLeafError = IsLeafError;
exports.LessThanEqualsFilter = LessThanEqualsFilter;
exports.LoopDetectError = LoopDetectError;
exports.MessageParser = MessageParser;
exports.MessageParserError = MessageParserError;
exports.MessageResponseStatus = MessageResponseStatus;
exports.ModifyDNRequest = ModifyDNRequest;
exports.ModifyDNResponse = ModifyDNResponse;
exports.ModifyRequest = ModifyRequest;
exports.ModifyResponse = ModifyResponse;
exports.MoreResultsToReturnError = MoreResultsToReturnError;
exports.NamingViolationError = NamingViolationError;
exports.NoObjectClassModsError = NoObjectClassModsError;
exports.NoResultError = NoResultError;
exports.NoSuchAttributeError = NoSuchAttributeError;
exports.NoSuchObjectError = NoSuchObjectError;
exports.NotAllowedOnNonLeafError = NotAllowedOnNonLeafError;
exports.NotAllowedOnRDNError = NotAllowedOnRDNError;
exports.NotFilter = NotFilter;
exports.ObjectClassViolationError = ObjectClassViolationError;
exports.OperationsError = OperationsError;
exports.OrFilter = OrFilter;
exports.PagedResultsControl = PagedResultsControl;
exports.PasswordPolicyControl = PasswordPolicyControl;
exports.PasswordPolicyError = PasswordPolicyError;
exports.PersistentSearchControl = PersistentSearchControl;
exports.PresenceFilter = PresenceFilter;
exports.ProtocolError = ProtocolError;
exports.ProtocolOperation = ProtocolOperation;
exports.ResultCodeError = ResultCodeError;
exports.ResultsTooLargeError = ResultsTooLargeError;
exports.SASL_MECHANISMS = SASL_MECHANISMS;
exports.SaslBindInProgressError = SaslBindInProgressError;
exports.SearchEntry = SearchEntry;
exports.SearchFilter = SearchFilter;
exports.SearchReference = SearchReference;
exports.SearchRequest = SearchRequest;
exports.SearchResponse = SearchResponse;
exports.ServerSideSortingRequestControl = ServerSideSortingRequestControl;
exports.SizeLimitExceededError = SizeLimitExceededError;
exports.StatusCodeParser = StatusCodeParser;
exports.StrongAuthRequiredError = StrongAuthRequiredError;
exports.SubstringFilter = SubstringFilter;
exports.TLSNotSupportedError = TLSNotSupportedError;
exports.TimeLimitExceededError = TimeLimitExceededError;
exports.TypeOrValueExistsError = TypeOrValueExistsError;
exports.UnavailableCriticalExtensionError = UnavailableCriticalExtensionError;
exports.UnavailableError = UnavailableError;
exports.UnbindRequest = UnbindRequest;
exports.UndefinedTypeError = UndefinedTypeError;
exports.UnknownStatusCodeError = UnknownStatusCodeError;
exports.UnwillingToPerformError = UnwillingToPerformError;
exports.decodePostalAddress = decodePostalAddress;
exports.encodePostalAddress = encodePostalAddress;
exports.escapeFilter = escapeFilter;
