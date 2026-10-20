/** 结构化错误：CLI、原生工具与 MCP 都返回同一套错误码，避免“失败但看起来成功”。 */
export const ERROR_CODES = {
    VALIDATION_FAILED: 'VALIDATION_FAILED',
    NOT_FOUND: 'NOT_FOUND',
    NETWORK_BLOCKED: 'NETWORK_BLOCKED',
    NETWORK_FAILED: 'NETWORK_FAILED',
    STORAGE_FAILED: 'STORAGE_FAILED',
    CONFIG_FAILED: 'CONFIG_FAILED',
    UNSUPPORTED: 'UNSUPPORTED',
    INTERNAL: 'INTERNAL',
};
export class ArtError extends Error {
    code;
    details;
    retryable;
    constructor(message, options = {}) {
        super(message);
        this.name = 'ArtError';
        this.code = options.code ?? ERROR_CODES.INTERNAL;
        this.details = options.details ?? {};
        this.retryable = options.retryable ?? false;
    }
}
export class ValidationError extends ArtError {
    constructor(message, details = {}) {
        super(message, { code: ERROR_CODES.VALIDATION_FAILED, details });
        this.name = 'ValidationError';
    }
}
export class NotFoundError extends ArtError {
    constructor(message, details = {}) {
        super(message, { code: ERROR_CODES.NOT_FOUND, details });
        this.name = 'NotFoundError';
    }
}
export function describeError(error) {
    if (error instanceof ArtError) {
        return { success: false, error: { type: error.name, code: error.code, message: error.message, details: error.details, retryable: error.retryable } };
    }
    const message = error instanceof Error ? error.message : String(error);
    return { success: false, error: { type: error instanceof Error ? error.name : 'Error', code: ERROR_CODES.INTERNAL, message } };
}
export function asError(error) {
    return error instanceof Error ? error : new Error(String(error));
}
export class StorageError extends ArtError {
    constructor(message, details = {}) {
        super(message, { code: ERROR_CODES.STORAGE_FAILED, details });
        this.name = 'StorageError';
    }
}
export class ConfigError extends ArtError {
    constructor(message, details = {}) {
        super(message, { code: ERROR_CODES.CONFIG_FAILED, details });
        this.name = 'ConfigError';
    }
}
