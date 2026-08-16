#include <grpcpp/grpcpp.h>
#include <gtest/gtest.h>

#include <chrono>
#include <memory>
#include <string>
#include <thread>

#include "grpc_smoke.grpc.pb.h"

namespace {

class SmokeService final : public ros2_sdk::smoke::SmokeService::Service {
  grpc::Status Echo(grpc::ServerContext* /*context*/, const ros2_sdk::smoke::EchoRequest* request,
                    ros2_sdk::smoke::EchoResponse* response) override {
    response->set_payload(request->payload());
    return grpc::Status::OK;
  }
};

class GrpcSmokeTest : public ::testing::Test {
protected:
  void SetUp() override {
    grpc::ServerBuilder builder;
    builder.AddListeningPort("127.0.0.1:0", grpc::InsecureServerCredentials(), &port_);
    builder.RegisterService(&service_);
    server_ = builder.BuildAndStart();
    ASSERT_NE(server_, nullptr);
    server_thread_ = std::thread([this] { server_->Wait(); });
  }

  void TearDown() override {
    if (server_ != nullptr) {
      server_->Shutdown();
    }
    if (server_thread_.joinable()) {
      server_thread_.join();
    }
  }

  int port() const { return port_; }

private:
  SmokeService service_;
  std::unique_ptr<grpc::Server> server_;
  std::thread server_thread_;
  int port_{0};
};

TEST_F(GrpcSmokeTest, UnaryRpcRoundTripsThroughGeneratedCode) {
  const auto channel = grpc::CreateChannel("127.0.0.1:" + std::to_string(port()),
                                           grpc::InsecureChannelCredentials());
  const auto stub = ros2_sdk::smoke::SmokeService::NewStub(channel);

  ros2_sdk::smoke::EchoRequest request;
  request.set_payload("grpc-smoke");
  ros2_sdk::smoke::EchoResponse response;
  grpc::ClientContext context;
  context.set_deadline(std::chrono::system_clock::now() + std::chrono::seconds(2));

  const grpc::Status status = stub->Echo(&context, request, &response);

  ASSERT_TRUE(status.ok()) << status.error_message();
  EXPECT_EQ(response.payload(), "grpc-smoke");
}

}  // namespace
