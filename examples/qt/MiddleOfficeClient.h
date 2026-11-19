#pragma once
#include <QObject>
#include <functional>
#include <utility>
#include <QJsonDocument>
#include <QJsonObject>
#include <QNetworkAccessManager>
#include <QNetworkReply>
#include <QNetworkRequest>
#include <QTimer>
#include <QUrl>

// Add Qt6::Network to the existing Qt project's target_link_libraries.
// Construct in the BusinessEngine thread. The callback runs in that thread.
class MiddleOfficeClient : public QObject {
public:
    using Callback = std::function<void(int, const QJsonObject&)>;

    explicit MiddleOfficeClient(QString baseUrl, QByteArray token = {}, QObject* parent = nullptr)
        : QObject(parent), baseUrl_(std::move(baseUrl)), token_(std::move(token)), manager_(this) {}

    void request(const QByteArray& method, const QString& path, const QJsonObject& payload, Callback callback) {
        QNetworkRequest request{QUrl(baseUrl_ + path)};
        request.setHeader(QNetworkRequest::ContentTypeHeader, QStringLiteral("application/json"));
        if (!token_.isEmpty()) request.setRawHeader("Authorization", "Bearer " + token_);
        const QByteArray body = method == "GET" ? QByteArray{} : QJsonDocument(payload).toJson(QJsonDocument::Compact);
        auto* reply = manager_.sendCustomRequest(request, method, body);
        QTimer::singleShot(5000, reply, [reply] { if (reply->isRunning()) reply->abort(); });
        connect(reply, &QNetworkReply::finished, this, [reply, callback = std::move(callback)] {
            const int status = reply->attribute(QNetworkRequest::HttpStatusCodeAttribute).toInt();
            auto result = QJsonDocument::fromJson(reply->readAll()).object();
            if (reply->error() != QNetworkReply::NoError && result.isEmpty())
                result = QJsonObject{{"error", QJsonObject{{"code", "transport_error"}, {"message", reply->errorString()}}}};
            callback(status, result);
            reply->deleteLater();
        });
    }

private:
    QString baseUrl_;
    QByteArray token_;
    QNetworkAccessManager manager_;
};
